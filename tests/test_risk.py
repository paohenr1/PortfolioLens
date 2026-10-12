"""Independent volatility/drawdown examples and complete-series integrity checks."""

import subprocess
import sys
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal, localcontext
from fractions import Fraction

from django.test import SimpleTestCase

from ledger.performance import DailySeries, Performance, _percent, calculate_returns
from ledger.risk import calculate_daily_risk
from ledger.risk_chart import drawdown_chart
from tests.test_performance import example

D = Decimal
DAY = date(2020, 1, 2)


def fixture_series(values, flows=None):
    flows = flows or ["0"] * len(values)
    days, cursor = [DAY], DAY
    while len(days) < len(values):
        cursor += timedelta(days=1)
        if cursor.weekday() < 5 and cursor != date(2020, 1, 20):
            days.append(cursor)
    periods, linked, issue = [], Fraction(1), None
    for index in range(1, len(values)):
        pair, quotes = example(values[index - 1 : index + 1], flows[index - 1 : index + 1])
        pair = (replace(pair[0], as_of=days[index - 1]), replace(pair[1], as_of=days[index]))
        quotes = (replace(quotes[0], as_of=days[index - 1]), replace(quotes[1], as_of=days[index]))
        result = calculate_returns(pair, quotes)
        periods.append(result.periods[0])
        issue = issue or result.issue
        if result.issue is None:
            linked *= Fraction(result.periods[0].before_flow_value) / Fraction(
                result.periods[0].start_value
            )
    return DailySeries(
        days[0], days[-1], tuple(periods), _percent(linked) if issue is None else None, issue
    )


class RiskCalculationTests(SimpleTestCase):
    def test_symmetric_returns_use_sample_not_population_variance(self):
        result = calculate_daily_risk(fixture_series(["100", "110", "99"]))
        self.assertEqual(result.daily_volatility_percent, D("14.1421"))
        self.assertEqual(result.maximum_drawdown_percent, D("10.0000"))
        self.assertIsNone(result.annualized_volatility_percent)

    def test_constant_return_has_zero_volatility_and_no_drawdown_episode(self):
        result = calculate_daily_risk(fixture_series(["100", "110", "121"]))
        self.assertEqual(result.daily_volatility_percent, D(0))
        self.assertEqual(str(result.maximum_drawdown_percent), "0.0000")
        self.assertIsNone(result.peak_date)
        self.assertIsNone(result.trough_date)
        self.assertIsNone(result.recovery_date)

    def test_one_return_has_drawdown_but_no_sample_volatility(self):
        result = calculate_daily_risk(fixture_series(["100", "90"]))
        self.assertEqual(result.maximum_drawdown_percent, D("10.0000"))
        self.assertIsNone(result.daily_volatility_percent)
        self.assertIn("two session", result.volatility_issue)
        self.assertEqual(result.peak_date, DAY)
        self.assertEqual(result.trough_date, date(2020, 1, 3))

    def test_twenty_observations_enable_exact_variance_annualization(self):
        # Each pair of 100% and -50% returns restores the original dollar value.
        result = calculate_daily_risk(fixture_series(["100", "200"] * 10 + ["100"]))
        self.assertEqual(result.observations, 20)
        self.assertEqual(result.daily_volatility_percent, D("76.9484"))
        # Sample variance = 11.25/19; scaling it by 252 gives 2835/19.
        self.assertEqual(result.annualized_volatility_percent, D("1221.5176"))
        self.assertIsNone(result.annualization_issue)

    def test_nineteen_returns_withhold_annualization(self):
        result = calculate_daily_risk(fixture_series(["100"] * 20))
        self.assertEqual(result.observations, 19)
        self.assertEqual(result.daily_volatility_percent, D(0))
        self.assertIsNone(result.annualized_volatility_percent)
        self.assertIn("twenty", result.annualization_issue)

    def test_peak_trough_recovery_use_first_deepest_episode(self):
        result = calculate_daily_risk(fixture_series(["100", "120", "90", "120", "96"]))
        self.assertEqual(result.maximum_drawdown_percent, D("25.0000"))
        self.assertEqual(
            (result.peak_date, result.trough_date, result.recovery_date),
            (date(2020, 1, 3), date(2020, 1, 6), date(2020, 1, 7)),
        )
        self.assertEqual(result.rows[-1].drawdown_percent, D("-20.0000"))

    def test_later_deeper_episode_replaces_recovered_episode(self):
        result = calculate_daily_risk(fixture_series(["100", "120", "96", "120", "90"]))
        self.assertEqual(result.maximum_drawdown_percent, D(25))
        self.assertEqual(result.peak_date, date(2020, 1, 7))
        self.assertEqual(result.trough_date, date(2020, 1, 8))
        self.assertIsNone(result.recovery_date)

    def test_equal_depth_retains_first_episode(self):
        result = calculate_daily_risk(fixture_series(["100", "80", "100", "80"]))
        self.assertEqual(result.maximum_drawdown_percent, D(20))
        self.assertEqual(result.trough_date, date(2020, 1, 3))
        self.assertEqual(result.recovery_date, date(2020, 1, 6))

    def test_equal_highs_use_the_latest_peak_before_a_decline(self):
        result = calculate_daily_risk(fixture_series(["100", "110", "110", "99"]))
        self.assertEqual(result.peak_date, date(2020, 1, 6))

    def test_cash_only_funding_and_withdrawal_do_not_create_risk(self):
        result = calculate_daily_risk(fixture_series(["100", "150", "125"], ["0", "50", "-25"]))
        self.assertEqual(result.daily_volatility_percent, D(0))
        self.assertEqual(result.maximum_drawdown_percent, D(0))

    def test_deposits_cannot_create_a_recovery_from_investment_loss(self):
        result = calculate_daily_risk(fixture_series(["100", "100", "200"], ["0", "10", "100"]))
        self.assertEqual(result.maximum_drawdown_percent, D(10))
        self.assertEqual(result.rows[-1].drawdown_percent, D(-10))
        self.assertIsNone(result.recovery_date)

    def test_terminal_total_loss_reaches_one_hundred_percent_drawdown(self):
        result = calculate_daily_risk(fixture_series(["100", "110", "0"]))
        self.assertEqual(result.maximum_drawdown_percent, D(100))
        self.assertEqual(result.rows[-1].drawdown_percent, D(-100))
        self.assertIsNone(result.recovery_date)

    def test_zero_opening_and_empty_restart_withhold_all_risk(self):
        for values in (["0", "100"], ["100", "0", "100"]):
            result = calculate_daily_risk(fixture_series(values))
            self.assertIsNone(result.maximum_drawdown_percent)
            self.assertIsNone(result.daily_volatility_percent)
            self.assertEqual(result.rows, ())

    def test_missing_row_withholds_whole_risk_and_no_partial_chart(self):
        original = fixture_series(["100", "110", "99", "100"])
        bad = replace(
            original,
            periods=(
                *original.periods[:1],
                replace(original.periods[1], return_percent=None, issue="Missing close"),
                original.periods[2],
            ),
        )
        result = calculate_daily_risk(bad)
        self.assertIsNone(result.maximum_drawdown_percent)
        self.assertIsNone(result.daily_volatility_percent)
        self.assertIsNone(drawdown_chart(result))

    def test_malformed_continuity_dates_and_series_metadata_fail_closed(self):
        original = fixture_series(["100", "110", "99"])
        for bad in (
            replace(original, start_date=date(2020, 1, 1)),
            replace(original, end_date=date(2020, 1, 10)),
            replace(
                original, periods=(replace(original.periods[0], end_date=DAY), original.periods[1])
            ),
            replace(
                original,
                periods=(original.periods[0], replace(original.periods[1], start_date=DAY)),
            ),
            replace(original, return_percent=D(999)),
            replace(original, return_percent=D("sNaN")),
        ):
            with self.subTest(series=bad):
                self.assertIsNone(calculate_daily_risk(bad).maximum_drawdown_percent)

    def test_bad_money_reconciliation_and_display_returns_fail_closed(self):
        original = fixture_series(["100", "110", "99"])
        for changes in (
            {"start_value": D("NaN")},
            {"end_value": D("Infinity")},
            {"before_flow_value": D(-1)},
            {"start_value": D("100.001")},
            {"external_flow": D(1)},
            {"return_percent": D(0)},
            {"return_percent": D("sNaN")},
            {"before_flow_value": D(109)},
        ):
            bad = replace(
                original, periods=(replace(original.periods[0], **changes), original.periods[1])
            )
            self.assertIsNone(calculate_daily_risk(bad).maximum_drawdown_percent)

    def test_cash_flow_boundary_returns_are_not_a_daily_risk_series(self):
        original = fixture_series(["100", "110", "99"])
        period = Performance(
            original.start_date, original.end_date, original.periods, original.return_percent, None
        )
        self.assertIsNone(calculate_daily_risk(period).daily_volatility_percent)

    def test_unrounded_returns_can_have_volatility_when_display_rounds_to_zero(self):
        original = fixture_series(["1000000.00", "1000000.40", "1000000.00"])
        self.assertTrue(all(row.return_percent == D(0) for row in original.periods))
        self.assertEqual(calculate_daily_risk(original).daily_volatility_percent, D("0.0001"))

    def test_low_caller_precision_does_not_round_variance_or_drawdown(self):
        original = fixture_series(["100", "110", "99"])
        with localcontext() as context:
            context.prec = 2
            result = calculate_daily_risk(original)
        self.assertEqual(result.daily_volatility_percent, D("14.1421"))
        self.assertEqual(result.maximum_drawdown_percent, D("10.0000"))

    def test_empty_malformed_and_oversized_series_are_unavailable(self):
        original = fixture_series(["100", "110"])
        for bad in (
            None,
            replace(original, periods=()),
            replace(original, periods=None),
            replace(original, periods=original.periods * 90),
        ):
            self.assertIsNone(calculate_daily_risk(bad).maximum_drawdown_percent)

    def test_module_imports_without_django_initialization(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; import ledger.risk; assert 'django' not in sys.modules",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class DrawdownChartTests(SimpleTestCase):
    def test_calendar_coordinates_and_values_remain_inside_plot(self):
        result = calculate_daily_risk(fixture_series(["100", "120", "90", "120"]))
        chart = drawdown_chart(result)
        self.assertEqual([p.value for p in chart["points"]], [D(0), D(0), D(-25), D(0)])
        self.assertTrue(
            all(D(95) <= p.x <= D(875) and D(35) <= p.y <= D(285) for p in chart["points"])
        )
        self.assertEqual(chart["points"][2].y, D(285))
        self.assertEqual(chart["points"][0].x, D(95))
        self.assertEqual(chart["points"][-1].x, D(875))

    def test_constant_series_has_a_visible_finite_scale(self):
        chart = drawdown_chart(calculate_daily_risk(fixture_series(["100", "100", "100"])))
        self.assertTrue(all(p.y == D(35) for p in chart["points"]))
        self.assertEqual(chart["y_ticks"][-1][1], D(-1))

    def test_incomplete_series_produces_no_chart(self):
        original = fixture_series(["100", "110"])
        self.assertIsNone(drawdown_chart(calculate_daily_risk(replace(original, issue="Missing"))))

    def test_coordinates_do_not_depend_on_decimal_callers_precision(self):
        risk = calculate_daily_risk(fixture_series(["100", "120", "90", "120"]))
        expected = drawdown_chart(risk)
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(drawdown_chart(risk), expected)
