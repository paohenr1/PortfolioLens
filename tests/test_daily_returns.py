"""Session calendar and hand-calculated daily returns, without provider calls."""

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal, localcontext

from django.test import SimpleTestCase

from ledger.daily_return_forms import DailyReturnForm
from ledger.daily_returns import build_daily_plan, calculate_daily_returns, session_dates
from ledger.domain import EventInput, LedgerRuleError
from ledger.performance import PerformanceRuleError
from ledger.valuation import value_snapshot
from tests.test_ledger_domain import DAY, cash, trade
from tests.test_valuation import IDENTIFIER, history

D = Decimal
END = date(2020, 1, 8)
MIDDLE = date(2020, 1, 6)


def series(events, prices=None, end=END):
    points = build_daily_plan(events, DAY, end)
    values = tuple(
        value_snapshot(
            point.analysis,
            point.as_of,
            {IDENTIFIER: history((prices or {}).get(point.as_of, "10"), as_of=point.as_of)},
            {IDENTIFIER: "XNYS"},
        )
        for point in points
    )
    return points, values


class DailyReturnTests(SimpleTestCase):
    def test_weekends_are_skipped_and_friday_to_monday_is_one_period(self):
        points, values = series([cash()])
        self.assertEqual(
            [p.as_of for p in points], [DAY, date(2020, 1, 3), MIDDLE, date(2020, 1, 7), END]
        )
        result = calculate_daily_returns(points, values)
        self.assertEqual(len(result.periods), 4)
        self.assertEqual(result.periods[1].start_date, date(2020, 1, 3))
        self.assertEqual(result.periods[1].end_date, MIDDLE)

    def test_holiday_early_close_and_exceptional_closure_calendar(self):
        for start, end, excluded, included in (
            (date(2022, 6, 17), date(2022, 6, 21), date(2022, 6, 20), date(2022, 6, 21)),
            (date(2025, 1, 8), date(2025, 1, 10), date(2025, 1, 9), date(2025, 1, 10)),
            (date(2001, 9, 10), date(2001, 9, 17), date(2001, 9, 11), date(2001, 9, 17)),
            (date(2020, 11, 25), date(2020, 11, 30), date(2020, 11, 26), date(2020, 11, 27)),
        ):
            with self.subTest(start=start):
                days = session_dates(start, end)
                self.assertNotIn(excluded, days)
                self.assertIn(included, days)

    def test_endpoints_must_be_sessions_and_window_is_bounded(self):
        for start, end in (
            (DAY, DAY),
            (END, DAY),
            (DAY, date(2020, 1, 4)),
            (date(2020, 1, 1), END),
            (date(1999, 12, 30), DAY),
            (DAY, DAY + timedelta(days=90)),
        ):
            with self.subTest(start=start, end=end), self.assertRaises(PerformanceRuleError):
                session_dates(start, end)

    def test_complete_cash_only_funding_and_withdrawal_is_zero(self):
        result = calculate_daily_returns(
            *series(
                [
                    cash(),
                    cash(amount="50", event_date=MIDDLE),
                    cash("WITHDRAWAL", "10", event_date=END),
                ]
            )
        )
        self.assertEqual(result.return_percent, D("0.0000"))
        self.assertEqual([p.external_flow for p in result.periods], [D(0), D(50), D(0), D(-10)])

    def test_cash_inclusive_price_return_and_eod_funding(self):
        result = calculate_daily_returns(
            *series(
                [cash(), trade(price="10", fees="0"), cash(amount="50", event_date=MIDDLE)],
                {
                    DAY: "10.5",
                    date(2020, 1, 3): "12.25",
                    MIDDLE: "13",
                    date(2020, 1, 7): "14",
                    END: "15.5",
                },
            )
        )
        self.assertEqual(result.return_percent, D("4.8600"))
        self.assertEqual(result.periods[1].before_flow_value, D("1030.00"))
        self.assertEqual(result.periods[1].external_flow, D("50"))

    def test_splits_and_raw_prices_preserve_wealth(self):
        result = calculate_daily_returns(
            *series(
                [
                    cash(),
                    trade(price="10", fees="0"),
                    EventInput("SPLIT", MIDDLE, 1, IDENTIFIER, split_new=2, split_old=1),
                ],
                {MIDDLE: "5", date(2020, 1, 7): "5", END: "5"},
            )
        )
        self.assertEqual(result.return_percent, D("0.0000"))

    def test_dividends_and_fees_are_internal_return(self):
        result = calculate_daily_returns(
            *series(
                [
                    cash(),
                    trade(price="10", fees="0"),
                    EventInput("DIVIDEND", MIDDLE, 1, IDENTIFIER, amount=D(10)),
                    cash("FEE", "2", sequence=2, event_date=MIDDLE),
                ]
            )
        )
        self.assertEqual(result.return_percent, D("0.8000"))

    def test_non_session_activity_fails_without_assigning_it_to_monday(self):
        for kind in ("DEPOSIT", "FEE"):
            with self.assertRaisesMessage(PerformanceRuleError, "Non-session activity"):
                build_daily_plan([cash(), cash(kind, "10", event_date=date(2020, 1, 4))], DAY, END)

    def test_intraday_flow_funding_trade_is_rejected(self):
        with self.assertRaisesMessage(PerformanceRuleError, "same-day activity"):
            build_daily_plan(
                [cash(), cash(event_date=MIDDLE), trade(sequence=2, event_date=MIDDLE)], DAY, END
            )

    def test_future_bad_journal_is_validated_and_future_valid_activity_excluded(self):
        self.assertEqual(
            calculate_daily_returns(
                *series([cash(), cash(event_date=date(2020, 1, 9))])
            ).return_percent,
            D(0),
        )
        with self.assertRaises(LedgerRuleError):
            series([cash(), cash("WITHDRAWAL", "1001", event_date=date(2020, 1, 9))])

    def test_missing_session_invalidates_adjacent_returns_and_whole_period(self):
        points, values = series([cash(), trade(price="10", fees="0")])
        values = list(values)
        values[2] = replace(values[2], total_value=None)
        result = calculate_daily_returns(points, tuple(values))
        self.assertIsNone(result.return_percent)
        self.assertEqual(
            [p.return_percent is None for p in result.periods], [False, True, True, False]
        )

    def test_longer_than_16_sessions_links_without_rounded_daily_returns(self):
        points, values = series([cash()], end=date(2020, 3, 31))
        self.assertGreater(len(points), 16)
        self.assertEqual(calculate_daily_returns(points, values).return_percent, D(0))
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(calculate_daily_returns(*series([cash()])).return_percent, D(0))

    def test_zero_baseline_is_undefined_and_zero_ending_value_is_total_loss(self):
        self.assertIsNone(calculate_daily_returns(*series([])).return_percent)
        points, values = series(
            [cash(), trade(quantity="100", price="10", fees="0")],
            {date(2020, 1, 3): "0", MIDDLE: "0", date(2020, 1, 7): "0", END: "0"},
        )
        self.assertIsNone(calculate_daily_returns(points, values).return_percent)
        self.assertEqual(calculate_daily_returns(points[:2], values[:2]).return_percent, D(-100))

    def test_matching_dates_and_lengths_required(self):
        points, values = series([cash()])
        with self.assertRaises(PerformanceRuleError):
            calculate_daily_returns(points, values[:2])
        with self.assertRaises(PerformanceRuleError):
            calculate_daily_returns(tuple(reversed(points)), values)
        invalid = (*values[:-1], replace(values[-1], as_of=DAY))
        self.assertIsNone(calculate_daily_returns(points, invalid).return_percent)

    def test_default_form_uses_actual_sessions_and_needs_confirmation(self):
        initial = DailyReturnForm().initial
        self.assertGreater(len(session_dates(initial["start_date"], initial["end_date"])), 2)
        data = {"start_date": DAY, "end_date": END}
        self.assertFalse(DailyReturnForm(data).is_valid())
        self.assertTrue(DailyReturnForm({**data, "timing_checked": "on"}).is_valid())

    def test_skipped_session_plan_is_rejected_even_with_complete_endpoint_values(self):
        points, values = series([cash()])
        with self.assertRaisesMessage(PerformanceRuleError, "every consecutive session"):
            calculate_daily_returns((points[0], points[-1]), (values[0], values[-1]))

    def test_cash_flow_boundary_cap_is_preserved(self):
        end = date(2020, 2, 28)
        events = [cash(event_date=day) for day in session_dates(DAY, end)[:17]]
        with self.assertRaisesMessage(PerformanceRuleError, "16 valuation dates"):
            build_daily_plan(events, DAY, end)
