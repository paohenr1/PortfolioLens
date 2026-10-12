"""Hand-calculated comparisons, exact alignment, and conservative provenance checks."""

import subprocess
import sys
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal, localcontext

from django.test import SimpleTestCase

from ledger.benchmark_chart import comparison_chart
from ledger.benchmarks import calculate_comparison
from market_data.contracts import DailyPrice, PriceHistory
from tests.test_ledger import REFERENCE
from tests.test_risk import fixture_series

D = Decimal
BENCHMARK_ID = "sec_fixture_benchmark"
BENCHMARK_REFERENCE = replace(REFERENCE, security=replace(REFERENCE.security, id=BENCHMARK_ID))


def benchmark_history(series, prices=None):
    days = (series.start_date, *(row.end_date for row in series.periods))
    prices = prices or ["50"] * len(days)
    return PriceHistory(
        BENCHMARK_REFERENCE.security,
        tuple(
            DailyPrice(day, D("999"), D(value), False)
            for day, value in zip(days, prices, strict=True)
        ),
        series.start_date,
        series.end_date,
        REFERENCE.retrieved_at,
        True,
    )


class BenchmarkCalculationTests(SimpleTestCase):
    def setUp(self):
        self.series = fixture_series(["100", "110", "99"])
        self.history = benchmark_history(self.series, ["50", "55", "60"])

    def calculate(self, series=None, reference=None, history=None):
        return calculate_comparison(
            series or self.series,
            reference or BENCHMARK_REFERENCE,
            history or self.history,
            BENCHMARK_ID,
        )

    def test_hand_calculated_linked_returns_and_percentage_point_gap(self):
        result = self.calculate()
        self.assertEqual(result.portfolio_return_percent, D(-1))
        self.assertEqual(result.benchmark_return_percent, D(20))
        self.assertEqual(result.difference_points, D(-21))
        self.assertEqual(result.rows[1].benchmark_return_percent, D("9.0909"))
        self.assertEqual(result.rows[0].difference_points, D(0))
        self.assertEqual(result.reference, BENCHMARK_REFERENCE)
        self.assertEqual(result.retrieved_at, self.history.retrieved_at)

    def test_external_funding_does_not_enter_benchmark_or_portfolio_return(self):
        series = fixture_series(["100", "200", "220"], ["0", "100", "0"])
        result = self.calculate(series=series, history=benchmark_history(series))
        self.assertEqual(result.portfolio_return_percent, D(10))
        self.assertEqual(result.benchmark_return_percent, D(0))
        self.assertEqual(result.difference_points, D(10))

    def test_adjusted_closes_are_used_without_raw_close_fallback(self):
        result = self.calculate()
        self.assertEqual(result.benchmark_return_percent, D(20))
        missing = replace(self.history.observations[1], adjusted_close=None)
        result = self.calculate(
            history=replace(
                self.history,
                observations=(self.history.observations[0], missing, self.history.observations[2]),
            )
        )
        self.assertIsNone(result.benchmark_return_percent)
        self.assertEqual(result.rows, ())

    def test_missing_middle_session_cannot_be_bridged_by_available_endpoints(self):
        result = self.calculate(
            history=replace(self.history, observations=self.history.observations[::2])
        )
        self.assertIsNone(result.difference_points)

    def test_duplicate_or_extra_or_shifted_dates_fail_closed(self):
        points = self.history.observations
        variants = (
            (points[0], points[0], points[2]),
            (*points, replace(points[1], date=points[1].date + timedelta(days=1))),
            (points[0], replace(points[1], date=points[1].date + timedelta(days=1)), points[2]),
            tuple(reversed(points)),
        )
        for observations in variants:
            with self.subTest(observations=observations):
                self.assertIsNone(
                    self.calculate(
                        history=replace(self.history, observations=observations)
                    ).difference_points
                )

    def test_incomplete_pagination_or_wrong_range_is_unavailable(self):
        for changes in (
            {"pagination_complete": False},
            {"start_date": self.series.start_date - timedelta(days=1)},
            {"end_date": self.series.end_date + timedelta(days=1)},
        ):
            with self.subTest(changes=changes):
                self.assertIsNone(
                    self.calculate(
                        history=replace(self.history, **changes)
                    ).benchmark_return_percent
                )

    def test_security_currency_and_venue_must_match_supported_reference(self):
        for changes in (
            {"id": "other"},
            {"currency": "CAD"},
            {"exchange_mic": "XNAS"},
            {"exchange_mic": None},
        ):
            with self.subTest(changes=changes):
                result = self.calculate(
                    history=replace(
                        self.history, security=replace(self.history.security, **changes)
                    )
                )
                self.assertIsNone(result.difference_points)
        foreign = replace(
            BENCHMARK_REFERENCE, security=replace(BENCHMARK_REFERENCE.security, exchange_mic="XTSE")
        )
        self.assertIsNone(self.calculate(reference=foreign).difference_points)

    def test_reference_or_history_requires_aware_retrieval_time(self):
        self.assertIsNone(
            self.calculate(
                reference=replace(
                    BENCHMARK_REFERENCE, retrieved_at=REFERENCE.retrieved_at.replace(tzinfo=None)
                )
            ).difference_points
        )
        self.assertIsNone(
            self.calculate(history=replace(self.history, retrieved_at=None)).difference_points
        )

    def test_unknown_intraperiod_or_invalid_adjusted_price_cannot_be_compared(self):
        for changes in (
            {"intraperiod": True},
            {"intraperiod": None},
            *(
                {"adjusted_close": value}
                for value in (
                    None,
                    D("NaN"),
                    D("sNaN"),
                    D("Infinity"),
                    D(-1),
                    D("1e13"),
                    D("1e-19"),
                    50,
                )
            ),
        ):
            with self.subTest(changes=changes):
                points = (
                    self.history.observations[0],
                    replace(self.history.observations[1], **changes),
                    self.history.observations[2],
                )
                self.assertIsNone(
                    self.calculate(
                        history=replace(self.history, observations=points)
                    ).difference_points
                )

    def test_zero_opening_price_and_restart_are_undefined(self):
        for prices in (["0", "50", "60"], ["50", "0", "60"]):
            self.assertIsNone(
                self.calculate(history=benchmark_history(self.series, prices)).difference_points
            )

    def test_terminal_benchmark_total_loss_is_valid(self):
        result = self.calculate(history=benchmark_history(self.series, ["50", "55", "0"]))
        self.assertEqual(result.benchmark_return_percent, D(-100))
        self.assertEqual(result.difference_points, D(99))

    def test_incomplete_or_reconciled_invalid_portfolio_withholds_comparison(self):
        for series in (
            replace(self.series, issue="Missing quote"),
            replace(self.series, return_percent=D(100)),
            replace(
                self.series,
                periods=(
                    self.series.periods[0],
                    replace(self.series.periods[1], before_flow_value=D(100)),
                ),
            ),
        ):
            self.assertIsNone(self.calculate(series=series).difference_points)

    def test_gap_uses_unrounded_factors_not_displayed_percentages(self):
        series = fixture_series(["1000000", "1000000.49"])
        result = self.calculate(
            series=series, history=benchmark_history(series, ["1", "1.00000051"])
        )
        self.assertEqual(result.portfolio_return_percent, D(0))
        self.assertEqual(result.benchmark_return_percent, D("0.0001"))
        self.assertEqual(result.difference_points, D(0))

    def test_caller_decimal_precision_does_not_change_returns(self):
        expected = self.calculate()
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(self.calculate(), expected)

    def test_one_session_return_is_a_valid_comparison(self):
        series = fixture_series(["100", "110"])
        result = self.calculate(series=series, history=benchmark_history(series, ["50", "55"]))
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.difference_points, D(0))

    def test_pure_modules_import_without_django_or_provider_client(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; import ledger.benchmarks; import ledger.benchmark_chart; "
                "assert 'django' not in sys.modules; assert 'httpx' not in sys.modules",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class BenchmarkChartTests(SimpleTestCase):
    def result(self, values=None):
        series = fixture_series(values or ["100", "110", "99"])
        return calculate_comparison(
            series, BENCHMARK_REFERENCE, benchmark_history(series), BENCHMARK_ID
        )

    def test_both_series_share_baseline_and_bounded_date_coordinates(self):
        chart = comparison_chart(self.result())
        self.assertEqual(len(chart["points"]), 3)
        self.assertEqual(chart["points"][0].portfolio, D(0))
        self.assertEqual(chart["points"][0].benchmark, D(0))
        self.assertEqual(chart["points"][0].x, D(95))
        self.assertEqual(chart["points"][-1].x, D(875))
        self.assertTrue(
            all(
                D(35) <= p.y <= D(285) and D(35) <= p.benchmark_y <= D(285) for p in chart["points"]
            )
        )

    def test_constant_series_produces_finite_coordinates(self):
        chart = comparison_chart(self.result(["100", "100", "100"]))
        self.assertTrue(all(p.y == p.benchmark_y == D(160) for p in chart["points"]))

    def test_missing_comparison_has_no_chart(self):
        self.assertIsNone(comparison_chart(None))
        self.assertIsNone(comparison_chart(replace(self.result(), issue="Unavailable")))

    def test_caller_precision_does_not_change_chart_coordinates(self):
        result = self.result()
        expected = comparison_chart(result)
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(comparison_chart(result), expected)
