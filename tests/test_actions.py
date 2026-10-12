"""Hand-calculated dividends and split-aware FIFO conservation, not provider observations."""

from dataclasses import replace
from decimal import Decimal, localcontext

from django.test import SimpleTestCase

from ledger.domain import EventInput, LedgerRuleError, replay
from ledger.fifo import analyze
from tests.test_ledger_domain import DAY, cash, trade

D = Decimal


def split(new=2, old=1, sequence=3, security_id="sec_fixture_primary"):
    return EventInput("SPLIT", DAY, sequence, security_id, split_new=new, split_old=old)


def dividend(amount="5", sequence=3, security_id="sec_fixture_primary"):
    return EventInput("DIVIDEND", DAY, sequence, security_id, amount=D(amount))


class ActionAccountingTests(SimpleTestCase):
    def test_cash_dividend_adds_income_not_sale_gain_or_lot_basis(self):
        result = analyze([cash(), trade(), dividend()])
        self.assertEqual(result.cash, D("754.00"))
        self.assertEqual(result.net_dividends, D("5.00"))
        self.assertEqual(result.realized_gain, D("0.00"))
        self.assertEqual(result.open_cost_basis, D("251.00"))
        self.assertEqual(result.positions[0].quantity, D("10"))

    def test_dividend_receipt_after_position_closes_is_allowed(self):
        result = analyze([cash(), trade(), trade("SELL", "10", "30", "2", 3), dividend(sequence=4)])
        self.assertEqual(result.positions, ())
        self.assertEqual(result.realized_gain, D("47.00"))
        self.assertEqual(result.net_dividends, D("5.00"))
        self.assertEqual(result.cash, D("1052.00"))

    def test_forward_split_preserves_cash_and_cost_then_allocates_new_share_basis(self):
        events = [cash(), trade(), split()]
        self.assertEqual(replay(events).quantities["sec_fixture_primary"], D("20"))
        result = analyze(events + [trade("SELL", "8", "15", "2", 4)])
        self.assertEqual(result.cash, D("867.00"))
        self.assertEqual(result.sales[0].cost_basis, D("100.40"))
        self.assertEqual(result.realized_gain, D("17.60"))
        self.assertEqual(result.positions[0].quantity, D("12"))
        self.assertEqual(result.open_cost_basis, D("150.60"))

    def test_exact_reverse_split_and_final_sale_close_every_cent(self):
        events = [cash(), trade(), split(1, 10)]
        before = analyze(events)
        self.assertEqual(before.positions[0].quantity, D("1"))
        self.assertEqual(before.open_cost_basis, D("251.00"))
        after = analyze(events + [trade("SELL", "1", "300", "2", 4)])
        self.assertEqual(after.realized_gain, D("47.00"))
        self.assertEqual(after.positions, ())

    def test_partial_sale_before_split_does_not_allocate_old_sold_cost_twice(self):
        result = analyze(
            [
                cash(),
                trade(),
                trade("SELL", "4", "30", "2", 3),
                split(sequence=4),
                trade("SELL", "6", "15", "1", 5),
            ]
        )
        self.assertEqual([sale.cost_basis for sale in result.sales], [D("100.40"), D("75.30")])
        self.assertEqual(result.open_cost_basis, D("75.30"))
        self.assertEqual(result.realized_gain, D("31.30"))
        self.assertEqual(result.positions[0].quantity, D("6"))

    def test_reverse_split_original_equivalent_can_be_fractional_when_remaining_lot_is_exact(self):
        result = analyze(
            [
                cash(),
                trade(quantity="5", price="10", fees="0"),
                trade("SELL", "2", "10", "0", 3),
                split(1, 3, 4),
                trade("SELL", "1", "30", "0", 5),
            ]
        )
        self.assertEqual([sale.cost_basis for sale in result.sales], [D("20.00"), D("30.00")])
        self.assertEqual(result.positions, ())
        self.assertEqual(result.realized_gain, D("0.00"))

    def test_multiple_lots_and_repeated_splits_preserve_cost_and_fifo_order(self):
        result = analyze(
            [
                cash(),
                trade(quantity="3", price="10", fees="1"),
                trade(quantity="2", price="20", fees="2", sequence=3),
                split(2, 1, 4),
                split(3, 2, 5),
                trade("SELL", "12", "10", "3", 6),
            ]
        )
        self.assertEqual(result.sales[0].cost_basis, D("52.00"))
        self.assertEqual(result.realized_gain, D("65.00"))
        self.assertEqual(result.positions[0].quantity, D("3"))
        self.assertEqual(result.open_cost_basis, D("21.00"))
        self.assertEqual([part.quantity for part in result.sales[0].lots], [D("9"), D("3")])

    def test_split_targets_one_stable_id_and_excludes_later_buys(self):
        result = analyze(
            [
                cash(),
                trade(quantity="1", fees="0", security_id="one"),
                trade(quantity="1", fees="0", sequence=3, security_id="two"),
                split(sequence=4, security_id="one"),
                trade(quantity="1", fees="0", sequence=5, security_id="one"),
            ]
        )
        self.assertEqual(
            [(p.security_id, p.quantity) for p in result.positions],
            [("one", D("3")), ("two", D("1"))],
        )

    def test_same_day_order_controls_split_and_sale_availability(self):
        with self.assertRaisesMessage(LedgerRuleError, "short position"):
            analyze([cash(), trade(), trade("SELL", "15", "15", "0", 3), split(sequence=4)])
        result = analyze([split(), cash(), trade(), trade("SELL", "15", "15", "0", 4)])
        self.assertEqual(result.positions[0].quantity, D("5"))

    def test_fraction_rounding_rejected_per_lot_even_when_aggregate_is_exact(self):
        events = [
            cash(),
            trade(quantity="1", fees="0"),
            trade(quantity="2", fees="0", sequence=3),
            split(1, 3, 4),
        ]
        self.assertEqual(replay(events).quantities["sec_fixture_primary"], D("1"))
        with self.assertRaisesMessage(LedgerRuleError, "cash-in-lieu"):
            analyze(events)

    def test_split_requires_open_shares_and_does_not_round_into_zero_or_overflow(self):
        for events in (
            [cash(), split()],
            [cash(), trade(quantity="0.000001", price="10000", fees="0"), split(1, 2)],
            [
                cash(amount="1000000000000"),
                trade(quantity="1000000000", price="1", fees="0"),
                split(1000000, 1),
            ],
        ):
            with self.subTest(events=events), self.assertRaises(LedgerRuleError):
                analyze(events)

    def test_ratio_and_shapes_do_not_accept_ambiguous_cash_trades_or_boolean_terms(self):
        for event in (
            split(1, 1),
            split(0, 1),
            split(True, 2),
            split(2, None),
            split(1000001, 1),
            replace(split(), amount=D("0")),
            replace(split(), fees=D("1")),
            replace(dividend(), quantity=D("1")),
            replace(dividend(), fees=D("1")),
            replace(trade(), split_new=2, split_old=1),
            replace(dividend(), currency="CAD"),
        ):
            with self.subTest(event=event), self.assertRaises(LedgerRuleError):
                event.validate(DAY)

    def test_split_math_is_independent_of_caller_precision(self):
        with localcontext() as context:
            context.prec = 3
            result = analyze([cash(), trade(quantity="123.123456", price="1", fees="0"), split()])
        self.assertEqual(result.positions[0].quantity, D("246.246912"))
        self.assertEqual(result.open_cost_basis, D("123.12"))
