"""Independent hand-calculated stock risk examples and full-window rejection cases."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, Inexact, Rounded, localcontext
from fractions import Fraction

import exchange_calendars
from django.test import SimpleTestCase

from market_data.contracts import DailyPrice, PriceHistory, Security
from market_data.venues import SUPPORTED_MICS
from research.stock_risk import calculate_stock_risk, percent
from research.stock_risk_chart import stock_drawdown_chart

D = Decimal
DAY = date(2020, 1, 2)


def stock_history(values=("100", "110", "99"), *, adjusted=None):
    # Explicit January 2020 weekday grid; MLK Day is not a trading session.
    days, cursor = [], DAY
    while len(days) < len(values):
        if cursor.weekday() < 5 and cursor != date(2020, 1, 20):
            days.append(cursor)
        cursor += timedelta(days=1)
    return PriceHistory(
        Security("sec_fixture_primary", "TSTF", "Test-only stock", "XNYS", "USD"),
        tuple(
            DailyPrice(day, D(value), D(adj), False)
            for day, value, adj in zip(days, values, adjusted or values, strict=True)
        ),
        days[0],
        days[-1],
        datetime(2020, 3, 1, tzinfo=UTC),
        True,
    )


class StockRiskCalculationTests(SimpleTestCase):
    def assert_unavailable(self, history, text=None, basis="raw"):
        result = calculate_stock_risk(history, basis)
        self.assertIsNotNone(result.issue)
        if text:
            self.assertIn(text, result.issue)
        self.assertIsNone(result.daily_volatility_percent)
        self.assertIsNone(result.annualized_volatility_percent)
        self.assertIsNone(result.maximum_drawdown_percent)
        self.assertEqual(result.observations, 0)
        self.assertEqual(result.rows, ())
        self.assertIsNone(stock_drawdown_chart(result))
        return result

    def test_sample_volatility_and_signed_rows_use_exact_simple_returns(self):
        result = calculate_stock_risk(stock_history(), "raw")
        self.assertEqual(result.observations, 2)
        self.assertEqual(result.expected_sessions, 3)
        # +10%, -10%: sample standard deviation sqrt(200), not population 10%.
        self.assertEqual(result.daily_volatility_percent, D("14.1421"))
        self.assertEqual(result.maximum_drawdown_percent, D("10.0000"))
        self.assertEqual([r.return_percent for r in result.rows], [None, D(10), D(-10)])
        self.assertEqual([r.drawdown_percent for r in result.rows], [D(0), D(0), D(-10)])

    def test_one_return_has_drawdown_and_withholds_daily_and_annual_volatility(self):
        result = calculate_stock_risk(stock_history(("100", "90")), "raw")
        self.assertEqual(result.maximum_drawdown_percent, D(10))
        self.assertEqual(result.peak_date, DAY)
        self.assertEqual(result.trough_date, date(2020, 1, 3))
        self.assertIsNone(result.recovery_date)
        self.assertIn("two", result.volatility_issue)
        self.assertIn("twenty", result.annualization_issue)

    def test_constant_returns_and_constant_prices_have_zero_risk_without_episode(self):
        for values in (("100", "110", "121"), ("100", "100", "100")):
            result = calculate_stock_risk(stock_history(values), "adjusted")
            self.assertEqual(str(result.daily_volatility_percent), "0.0000")
            self.assertEqual(str(result.maximum_drawdown_percent), "0.0000")
            self.assertIsNone(result.peak_date)
            self.assertIsNone(result.trough_date)
            self.assertIsNone(result.recovery_date)

    def test_twenty_returns_scale_unrounded_sample_variance(self):
        result = calculate_stock_risk(stock_history(["100", "200"] * 10 + ["100"]), "raw")
        # Twenty returns alternating +100%/-50%: sample variance = 11.25/19.
        self.assertEqual(result.observations, 20)
        self.assertEqual(result.daily_volatility_percent, D("76.9484"))
        self.assertEqual(result.annualized_volatility_percent, D("1221.5176"))
        self.assertIsNone(result.annualization_issue)

    def test_nineteen_returns_withhold_annualization(self):
        result = calculate_stock_risk(stock_history(["100"] * 20), "raw")
        self.assertEqual(result.observations, 19)
        self.assertEqual(result.daily_volatility_percent, D(0))
        self.assertIsNone(result.annualized_volatility_percent)

    def test_first_deepest_episode_and_first_recovery_are_preserved(self):
        result = calculate_stock_risk(stock_history(("100", "120", "90", "120", "90")), "raw")
        self.assertEqual(result.maximum_drawdown_percent, D(25))
        self.assertEqual(result.peak_date, date(2020, 1, 3))
        self.assertEqual(result.trough_date, date(2020, 1, 6))
        self.assertEqual(result.recovery_date, date(2020, 1, 7))

    def test_deeper_episode_replaces_prior_episode_and_its_recovery(self):
        result = calculate_stock_risk(stock_history(("100", "90", "100", "80")), "raw")
        self.assertEqual(result.maximum_drawdown_percent, D(20))
        self.assertEqual(result.peak_date, date(2020, 1, 6))
        self.assertEqual(result.trough_date, date(2020, 1, 7))
        self.assertIsNone(result.recovery_date)

    def test_repeated_equal_peaks_use_latest_peak_and_no_prior_window_peak(self):
        result = calculate_stock_risk(stock_history(("100", "100", "90")), "raw")
        self.assertEqual(result.peak_date, date(2020, 1, 3))
        self.assertEqual(result.maximum_drawdown_percent, D(10))

    def test_raw_and_adjusted_split_effects_are_separate_without_fallback(self):
        history = stock_history(("100", "50", "55"), adjusted=("50", "50", "55"))
        raw, adjusted = [calculate_stock_risk(history, basis) for basis in ("raw", "adjusted")]
        self.assertEqual(raw.maximum_drawdown_percent, D(50))
        self.assertEqual(adjusted.maximum_drawdown_percent, D(0))
        self.assertEqual(adjusted.daily_volatility_percent, D("7.0711"))
        missing = replace(history.observations[1], adjusted_close=None)
        history = replace(
            history, observations=(history.observations[0], missing, history.observations[2])
        )
        self.assert_unavailable(history, "selected close", "adjusted")
        self.assertIsNone(calculate_stock_risk(history, "raw").issue)

    def test_prices_are_not_rounded_to_cents_before_returns(self):
        result = calculate_stock_risk(stock_history(("0.000001", "0.0000011", "0.00000099")), "raw")
        self.assertEqual(result.daily_volatility_percent, D("14.1421"))
        self.assertEqual(result.maximum_drawdown_percent, D(10))

    def test_numeric_context_traps_and_small_exponents_do_not_change_results(self):
        history = stock_history()
        expected = calculate_stock_risk(history, "raw")
        with localcontext() as context:
            context.prec, context.Emax, context.Emin = 2, 2, -2
            context.traps[Inexact] = context.traps[Rounded] = True
            result = calculate_stock_risk(history, "raw")
            chart = stock_drawdown_chart(result)
            self.assertEqual(result, expected)
            self.assertEqual(chart["points"][-1]["y"], 285)

    def test_rational_percent_half_up_and_negative_zero(self):
        self.assertEqual(str(percent(Fraction(1, 2_000_000))), "0.0001")
        self.assertEqual(str(percent(Fraction(-1, 2_000_000))), "-0.0001")
        self.assertEqual(str(percent(Fraction(-1, 10_000_000))), "0.0000")

    def test_missing_session_or_endpoints_withholds_whole_sample(self):
        history = stock_history(("100", "110", "99", "105"))
        for index in (0, 1, 3):
            rows = history.observations[:index] + history.observations[index + 1 :]
            result = self.assert_unavailable(replace(history, observations=rows), "consecutive")
            self.assertEqual(result.expected_sessions, 4)

    def test_duplicate_unordered_and_non_session_dates_are_rejected(self):
        history = stock_history()
        for rows in (
            history.observations[::-1],
            history.observations + history.observations[:1],
            (
                history.observations[0],
                replace(history.observations[1], date=date(2020, 1, 4)),
                history.observations[2],
            ),
        ):
            self.assert_unavailable(replace(history, observations=rows), "consecutive")

    def test_partial_pagination_and_empty_responses_are_not_complete_market_coverage(self):
        self.assert_unavailable(replace(stock_history(), pagination_complete=False), "complete")
        self.assert_unavailable(replace(stock_history(), observations=()), "consecutive")

    def test_unknown_or_incomplete_period_status_withholds_all_statistics(self):
        for status in (True, None, 0):
            history = stock_history()
            rows = (replace(history.observations[0], intraperiod=status), *history.observations[1:])
            self.assert_unavailable(replace(history, observations=rows), "confirmed")

    def test_invalid_missing_zero_and_negative_selected_closes_are_rejected(self):
        for value in (
            None,
            100,
            True,
            D(0),
            D(-1),
            D("NaN"),
            D("Infinity"),
            D("1e13"),
            D("1e-19"),
            D("100.00000000000000000000000000"),
        ):
            history = stock_history()
            rows = (replace(history.observations[0], close=value), *history.observations[1:])
            self.assert_unavailable(replace(history, observations=rows), "positive")

    def test_unknown_or_foreign_venues_are_unavailable_without_currency_inference(self):
        history = stock_history()
        for mic in (None, "XLON", "OTCM"):
            self.assert_unavailable(
                replace(history, security=replace(history.security, exchange_mic=mic)), "venues"
            )
        for currency in (None, "CAD"):
            result = calculate_stock_risk(
                replace(history, security=replace(history.security, currency=currency)), "raw"
            )
            self.assertIsNone(result.issue)
            self.assertEqual(result.daily_volatility_percent, D("14.1421"))

    def test_all_supported_mics_share_explicit_us_equity_session_policy(self):
        history = stock_history()
        for mic in SUPPORTED_MICS:
            result = calculate_stock_risk(
                replace(history, security=replace(history.security, exchange_mic=mic)), "raw"
            )
            self.assertIsNone(result.issue)

    def test_weekend_and_holiday_endpoints_use_only_sessions_inside_window(self):
        history = stock_history(["100"] * 12)
        result = calculate_stock_risk(
            replace(history, start_date=date(2020, 1, 1), end_date=date(2020, 1, 20)), "raw"
        )
        self.assertIsNone(result.issue)
        self.assertEqual(result.rows[0].as_of, DAY)
        self.assertEqual(result.rows[-1].as_of, date(2020, 1, 17))
        self.assertEqual(result.expected_sessions, 12)

    def test_extraordinary_september_2001_closures_are_not_missing_sessions(self):
        history = stock_history(("100", "90"))
        rows = tuple(
            replace(row, date=day)
            for row, day in zip(
                history.observations, (date(2001, 9, 10), date(2001, 9, 17)), strict=True
            )
        )
        result = calculate_stock_risk(
            replace(history, observations=rows, start_date=rows[0].date, end_date=rows[-1].date),
            "raw",
        )
        self.assertIsNone(result.issue)
        self.assertEqual(result.observations, 1)

    def test_single_session_and_all_weekend_ranges_are_unavailable(self):
        self.assert_unavailable(stock_history(("100",)), "two sessions")
        history = replace(
            stock_history(), start_date=date(2020, 1, 4), end_date=date(2020, 1, 5), observations=()
        )
        self.assertEqual(self.assert_unavailable(history).expected_sessions, 0)

    def test_today_future_pre_2000_and_overlong_ranges_are_unavailable(self):
        history = stock_history()
        for start, end in (
            (date(1999, 12, 31), history.end_date),
            (DAY, DAY + timedelta(days=366)),
            (DAY, datetime.now(UTC).date()),
            (DAY, DAY - timedelta(days=1)),
            (None, history.end_date),
        ):
            self.assert_unavailable(
                replace(history, start_date=start, end_date=end), "completed dates"
            )

    def test_untrusted_contracts_metadata_and_naive_retrieval_are_unavailable(self):
        history = stock_history()
        for value in (
            None,
            replace(history, security=None),
            replace(history, observations=list(history.observations)),
            replace(history, observations=(None,)),
            replace(history, retrieved_at=None),
            replace(history, retrieved_at=history.retrieved_at.replace(tzinfo=None)),
            replace(history, security=replace(history.security, id="bad.id")),
        ):
            self.assert_unavailable(value)

    def test_unsupported_basis_is_a_programming_error(self):
        with self.assertRaises(ValueError):
            calculate_stock_risk(stock_history(), "automatic")

    def test_drawdown_chart_coordinates_are_bounded_and_exact_table_is_separate(self):
        result = calculate_stock_risk(stock_history(("100", "120", "90", "120")), "raw")
        chart = stock_drawdown_chart(result)
        self.assertEqual(chart["points"][0]["x"], 95)
        self.assertEqual(chart["points"][-1]["x"], 875)
        self.assertEqual(chart["points"][2]["y"], 285)
        self.assertEqual(chart["points"][2]["value"], D(-25))
        self.assertEqual(chart["y_ticks"][-1], (285, D(-25)))
        self.assertTrue(all(35 <= p["y"] <= 285 for p in chart["points"]))

    def test_zero_drawdown_chart_uses_one_percentage_point_span(self):
        chart = stock_drawdown_chart(
            calculate_stock_risk(stock_history(("100", "100", "100")), "raw")
        )
        self.assertTrue(all(p["y"] == 35 for p in chart["points"]))
        self.assertEqual(chart["y_ticks"][-1], (285, D(-1)))

    def test_full_leap_year_window_supports_more_than_portfolio_ninety_day_limit(self):
        history = stock_history()
        start, end = date(2020, 1, 1), date(2020, 12, 31)
        calendar = exchange_calendars.get_calendar(
            "XNYS", start=start - timedelta(days=7), end=end + timedelta(days=7)
        )
        days = tuple(point.date() for point in calendar.sessions_in_range(start, end))
        # Independent known 2020 count: 253 regular U.S. equity sessions.
        self.assertEqual(len(days), 253)
        rows = tuple(DailyPrice(day, D(100), D(100), False) for day in days)
        result = calculate_stock_risk(
            replace(history, observations=rows, start_date=start, end_date=end), "raw"
        )
        self.assertIsNone(result.issue)
        self.assertEqual(result.observations, 252)
        self.assertEqual(result.annualized_volatility_percent, D(0))

    def test_provider_price_bounds_can_produce_large_finite_percentages(self):
        result = calculate_stock_risk(stock_history(("1e-18", "1e12", "1e-18")), "raw")
        self.assertIsNone(result.issue)
        self.assertTrue(result.daily_volatility_percent.is_finite())
        self.assertEqual(result.maximum_drawdown_percent, D(100))
        self.assertEqual(result.rows[1].return_percent, percent(Fraction(10**30 - 1)))
