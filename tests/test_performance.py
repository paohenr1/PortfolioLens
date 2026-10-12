"""Independent cash-flow examples and end-of-day timing/precision constraints."""

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal, localcontext

from django.test import SimpleTestCase

from ledger.domain import EventInput, LedgerRuleError
from ledger.fifo import analyze
from ledger.performance import Boundary, PerformanceRuleError, build_plan, calculate_returns
from ledger.valuation import value_snapshot
from tests.test_ledger_domain import DAY, cash, trade
from tests.test_valuation import IDENTIFIER

D = Decimal
END = date(2020, 1, 8)


def example(values, flows=None):
    boundaries, valuations = [], []
    flows = flows or ["0"] * len(values)
    for index, (value, flow) in enumerate(zip(values, flows, strict=True)):
        day = DAY + timedelta(days=index)
        analysis = analyze([cash(amount=value)]) if D(value) > 0 else analyze([])
        boundaries.append(Boundary(day, analysis, D(flow)))
        valuations.append(value_snapshot(analysis, day, {}, {}))
    return tuple(boundaries), tuple(valuations)


class ReturnCalculationTests(SimpleTestCase):
    def test_two_ten_percent_periods_link_to_twenty_one_percent(self):
        result = calculate_returns(*example(["100", "110", "121"]))
        self.assertEqual(
            [period.return_percent for period in result.periods], [D("10.0000"), D("10.0000")]
        )
        self.assertEqual(result.return_percent, D("21.0000"))

    def test_deposit_is_removed_from_return_but_enters_next_opening_value(self):
        result = calculate_returns(*example(["100", "160", "176"], ["0", "50", "0"]))
        self.assertEqual(result.return_percent, D("21.0000"))
        self.assertEqual(result.periods[0].before_flow_value, D("110.00"))
        self.assertEqual(result.periods[1].start_value, D("160"))

    def test_withdrawal_is_added_back_and_does_not_become_a_loss(self):
        result = calculate_returns(*example(["100", "60", "66"], ["0", "-50", "0"]))
        self.assertEqual(result.return_percent, D("21.0000"))
        self.assertEqual(result.periods[0].before_flow_value, D("110.00"))

    def test_terminal_withdrawal_can_empty_portfolio_without_losing_return(self):
        result = calculate_returns(*example(["100", "0"], ["0", "-110"]))
        self.assertEqual(result.return_percent, D("10.0000"))

    def test_cash_contributions_alone_are_zero_return(self):
        result = calculate_returns(*example(["100", "200", "150"], ["0", "100", "-50"]))
        self.assertEqual(result.return_percent, D("0.0000"))

    def test_positive_opening_value_can_end_at_total_loss(self):
        result = calculate_returns(*example(["100", "0"]))
        self.assertEqual(result.return_percent, D("-100.0000"))

    def test_empty_opening_or_restart_has_no_defined_complete_return(self):
        for values in (["0", "100"], ["100", "0", "100"]):
            result = calculate_returns(*example(values))
            self.assertIsNone(result.return_percent)
            self.assertIn("positive opening", result.issue)

    def test_zero_growth_factor_remains_total_loss_after_new_funding(self):
        result = calculate_returns(*example(["100", "50", "55"], ["0", "50", "0"]))
        self.assertEqual(result.return_percent, D("-100.0000"))

    def test_missing_middle_valuation_withholds_both_adjacent_returns_and_total(self):
        boundaries, valuations = example(["100", "110", "121"])
        result = calculate_returns(
            boundaries, (valuations[0], replace(valuations[1], total_value=None), valuations[2])
        )
        self.assertIsNone(result.return_percent)
        self.assertTrue(all(period.return_percent is None for period in result.periods))

    def test_available_subperiod_is_retained_without_claiming_partial_total(self):
        boundaries, valuations = example(["100", "110", "121"])
        result = calculate_returns(
            boundaries, (*valuations[:2], replace(valuations[2], total_value=None))
        )
        self.assertEqual(result.periods[0].return_percent, D("10.0000"))
        self.assertIsNone(result.return_percent)

    def test_date_identity_cash_and_value_reconciliation_fail_closed(self):
        boundaries, valuations = example(["100", "110"])
        for invalid in (
            replace(valuations[1], as_of=END),
            replace(valuations[1], total_value=D("111")),
            replace(valuations[1], cash=D("111")),
            replace(valuations[1], total_value=D("NaN")),
            replace(valuations[1], total_value=D("110.001")),
        ):
            with self.subTest(valuation=invalid):
                self.assertIsNone(
                    calculate_returns(boundaries, (valuations[0], invalid)).return_percent
                )

    def test_negative_pre_flow_value_is_undefined(self):
        result = calculate_returns(*example(["100", "10"], ["0", "20"]))
        self.assertIsNone(result.return_percent)
        self.assertIn("cannot be negative", result.issue)

    def test_returns_do_not_depend_on_callers_decimal_precision_or_rounded_periods(self):
        inputs = example(["100", "101", "102"])
        with localcontext() as context:
            context.prec = 2
            result = calculate_returns(*inputs)
        self.assertEqual(result.return_percent, D("2.0000"))
        self.assertEqual(result.periods[1].return_percent, D("0.9901"))

    def test_long_large_exact_chain_does_not_overflow_display_precision(self):
        values = ["0.01"] * 16
        flows = ["0"] + ["-999999999999"] * 15
        result = calculate_returns(*example(values, flows))
        self.assertIsNotNone(result.return_percent)
        self.assertGreater(result.return_percent, D("1e100"))

    def test_missing_or_nonincreasing_boundary_plan_is_rejected(self):
        points, values = example(["100", "110"])
        for boundaries, valuations in (
            (points, values[:1]),
            (points[:1], values[:1]),
            (tuple(reversed(points)), values),
        ):
            with self.assertRaises(PerformanceRuleError):
                calculate_returns(boundaries, valuations)


class ReturnPlanTests(SimpleTestCase):
    def test_opening_flow_is_already_in_baseline_and_end_flow_is_a_boundary(self):
        plan = build_plan([cash(), trade(), cash(amount="50", event_date=END)], DAY, END)
        self.assertEqual([point.as_of for point in plan], [DAY, END])
        self.assertEqual([point.external_flow for point in plan], [D("0"), D("50")])
        self.assertEqual(plan[0].analysis.cash, D("749.00"))

    def test_flow_dates_create_boundaries_even_when_net_flow_is_zero(self):
        middle = DAY + timedelta(days=2)
        plan = build_plan(
            [cash(), cash(amount="50", event_date=middle), cash("WITHDRAWAL", "50", 2, middle)],
            DAY,
            END,
        )
        self.assertEqual([point.as_of for point in plan], [DAY, middle, END])
        self.assertEqual(plan[1].external_flow, D("0"))

    def test_fees_dividends_and_splits_are_internal_not_external_boundaries(self):
        middle = DAY + timedelta(days=2)
        events = [
            cash(),
            trade(),
            cash("FEE", "2", 1, middle),
            EventInput("DIVIDEND", middle, 2, IDENTIFIER, amount=D("5")),
            EventInput("SPLIT", middle, 3, IDENTIFIER, split_new=2, split_old=1),
        ]
        plan = build_plan(events, DAY, END)
        self.assertEqual(len(plan), 2)
        self.assertEqual(plan[1].analysis.cash, D("752.00"))
        self.assertEqual(plan[1].analysis.positions[0].quantity, D("20"))

    def test_flow_after_other_activity_is_supported_but_before_activity_is_rejected(self):
        middle = DAY + timedelta(days=2)
        for events in (
            [cash(), cash("FEE", "1", 1, middle), cash(sequence=2, event_date=middle)],
            [cash(), cash(event_date=middle), cash("FEE", "1", 2, middle)],
        ):
            if events[-1].kind == "FEE":
                with self.assertRaisesMessage(PerformanceRuleError, "same-day activity"):
                    build_plan(events, DAY, END)
            else:
                self.assertEqual(len(build_plan(events, DAY, END)), 3)

    def test_later_cash_flow_is_excluded_and_later_bad_journal_is_rejected(self):
        later = END + timedelta(days=1)
        self.assertEqual(len(build_plan([cash(), cash(event_date=later)], DAY, END)), 2)
        with self.assertRaises(LedgerRuleError):
            build_plan([cash(), cash("WITHDRAWAL", "1001", event_date=later)], DAY, END)

    def test_date_and_boundary_limits_fail_before_any_valuation(self):
        for start, end in (
            (DAY, DAY),
            (END, DAY),
            (date(1899, 1, 1), DAY),
            (DAY, DAY + timedelta(days=366)),
        ):
            with self.assertRaises(PerformanceRuleError):
                build_plan([cash()], start, end)
        events = [cash(event_date=DAY + timedelta(days=index)) for index in range(17)]
        with self.assertRaisesMessage(PerformanceRuleError, "16 valuation dates"):
            build_plan(events, DAY, DAY + timedelta(days=18))
