"""Independently calculated FIFO examples and exact conservation properties."""

from dataclasses import FrozenInstanceError, replace
from datetime import date
from decimal import Decimal, localcontext

from django.test import SimpleTestCase

from ledger.domain import LedgerRuleError
from ledger.fifo import analyze
from tests.test_ledger_domain import cash, trade

D = Decimal


class FIFOTests(SimpleTestCase):
    def test_original_journal_example_includes_buy_and_sell_fees_once(self):
        result = analyze(
            [
                cash(),
                trade(),
                trade("SELL", "4", "30", "2", 3),
                cash("WITHDRAWAL", "100", 4),
                cash("FEE", "3", 5),
            ]
        )
        self.assertEqual(result.cash, D("764.00"))
        self.assertEqual(result.open_cost_basis, D("150.60"))
        self.assertEqual(result.realized_gain, D("17.60"))
        self.assertEqual(result.standalone_fees, D("3.00"))
        position, sale = result.positions[0], result.sales[0]
        self.assertEqual(position.quantity, D("6"))
        self.assertEqual(sale.cost_basis, D("100.40"))
        self.assertEqual(sale.net_proceeds, D("118.00"))

    def test_fifo_sale_spans_oldest_lots_instead_of_average_cost(self):
        result = analyze(
            [
                cash(),
                trade(quantity="3", price="10", fees="1"),
                trade(quantity="2", price="20", fees="2", sequence=3),
                trade("SELL", "4", "30", "3", 4),
            ]
        )
        sale = result.sales[0]
        self.assertEqual(sale.cost_basis, D("52.00"))  # 31 + half of 42.
        self.assertEqual(sale.gain, D("65.00"))  # 120 - 3 - 52.
        self.assertEqual([lot.quantity for lot in sale.lots], [D("3"), D("1")])
        self.assertEqual([lot.acquisition_order for lot in sale.lots], [2, 3])
        self.assertEqual(result.open_cost_basis, D("21.00"))
        self.assertEqual(result.positions[0].quantity, D("1"))

    def test_complete_sale_keeps_realized_history_with_no_open_position(self):
        result = analyze([cash(), trade(), trade("SELL", "10", "30", "2", 3)])
        self.assertEqual(result.positions, ())
        self.assertEqual(result.open_cost_basis, D("0.00"))
        self.assertEqual(result.sales[0].cost_basis, D("251.00"))
        self.assertEqual(result.realized_gain, D("47.00"))

    def test_realized_losses_keep_their_sign(self):
        result = analyze(
            [
                cash(),
                trade(quantity="2", price="10", fees="1"),
                trade("SELL", "2", "8", "1", 3),
            ]
        )
        self.assertEqual(result.realized_gain, D("-6.00"))

    def test_no_sale_has_zero_realized_gain_and_no_market_value(self):
        result = analyze([cash(), trade()])
        self.assertEqual(result.realized_gain, D("0.00"))
        self.assertEqual(result.sales, ())
        self.assertEqual(result.open_cost_basis, D("251.00"))
        self.assertFalse(hasattr(result, "market_value"))

    def test_empty_and_cash_only_journals_do_not_turn_contributions_into_gain(self):
        for events, expected_cash in (([], "0.00"), ([cash()], "1000.00")):
            result = analyze(events)
            self.assertEqual(result.cash, D(expected_cash))
            self.assertEqual(result.realized_gain, D("0.00"))
            self.assertEqual(result.positions, ())

    def test_withdrawals_and_standalone_fees_do_not_change_sale_gain(self):
        events = [cash(), trade(), trade("SELL", "4", "30", "2", 3)]
        before = analyze(events)
        after = analyze(events + [cash("WITHDRAWAL", "100", 4), cash("FEE", "3", 5)])
        self.assertEqual(before.sales, after.sales)
        self.assertEqual(before.positions, after.positions)
        self.assertEqual(after.cash, before.cash - D("103"))

    def test_fractional_shares_and_subcent_execution_price_use_rounded_gross(self):
        result = analyze(
            [
                cash(amount="1"),
                trade(quantity="0.5", price="0.01", fees="0"),
                trade("SELL", "0.25", "0.04", "0", 3),
            ]
        )
        self.assertEqual(result.sales[0].cost_basis, D("0.01"))
        self.assertEqual(result.positions[0].quantity, D("0.25"))
        self.assertEqual(result.open_cost_basis, D("0.00"))
        self.assertEqual(result.realized_gain, D("0.00"))

    def test_cumulative_half_cent_rounding_conserves_entire_lot(self):
        events = [cash(), trade(quantity="3", price="0.01", fees="0.01")]
        results = []
        for sequence in (3, 4, 5):
            events.append(trade("SELL", "1", "1", "0", sequence))
            results.append(analyze(events))
        self.assertEqual(
            [result.sales[-1].cost_basis for result in results], [D("0.01"), D("0.02"), D("0.01")]
        )
        self.assertEqual(
            [result.open_cost_basis for result in results], [D("0.03"), D("0.01"), D("0.00")]
        )
        self.assertEqual(results[-1].realized_gain, D("2.96"))

    def test_equal_cumulative_sold_quantity_has_equal_basis_despite_sale_batching(self):
        opening = [cash(), trade(quantity="6", price="0.01", fees="0.01")]
        one = analyze(opening + [trade("SELL", "3", "1", "0", 3)])
        split = analyze(opening + [trade("SELL", "1", "1", "0", n) for n in (3, 4, 5)])
        self.assertEqual(one.open_cost_basis, D("0.03"))
        self.assertEqual(one.open_cost_basis, split.open_cost_basis)
        self.assertEqual(one.realized_gain, split.realized_gain)
        self.assertEqual(sum((sale.cost_basis for sale in split.sales), D("0")), D("0.04"))

    def test_many_fractional_sales_close_without_creating_or_losing_a_cent(self):
        opening = [cash(), trade(quantity="1", price="0.01", fees="0")]
        sales = [trade("SELL", "0.1", "1", "0", n) for n in range(3, 13)]
        result = analyze(opening + sales)
        self.assertEqual(result.positions, ())
        self.assertEqual(
            [sale.cost_basis for sale in result.sales],
            [D("0.00")] * 4 + [D("0.01")] + [D("0.00")] * 5,
        )
        self.assertEqual(result.realized_gain, D("0.99"))

    def test_explicit_dates_and_same_day_order_override_input_arrival_order(self):
        opening = cash(event_date=date(2020, 1, 1))
        old = trade(quantity="1", price="10", fees="0", event_date=date(2020, 1, 2))
        newer = trade(quantity="1", price="20", fees="0", sequence=1, event_date=date(2020, 1, 3))
        sale = trade("SELL", "1", "30", "0", 2, event_date=date(2020, 1, 3))
        result = analyze([sale, newer, opening, old])
        self.assertEqual(result.sales[0].cost_basis, D("10.00"))
        self.assertEqual(result.positions[0].cost_basis, D("20.00"))

    def test_security_ids_keep_independent_queues(self):
        result = analyze(
            [
                cash(),
                trade(quantity="1", price="10", fees="0", security_id="one"),
                trade(quantity="1", price="20", fees="0", sequence=3, security_id="two"),
                trade("SELL", "1", "30", "0", 4, security_id="two"),
            ]
        )
        self.assertEqual(result.positions[0].security_id, "one")
        self.assertEqual(result.positions[0].cost_basis, D("10.00"))
        self.assertEqual(result.sales[0].cost_basis, D("20.00"))

    def test_buy_after_full_close_starts_a_new_fifo_lot(self):
        result = analyze(
            [
                cash(),
                trade(quantity="1", price="10", fees="0"),
                trade("SELL", "1", "20", "0", 3),
                trade(quantity="1", price="30", fees="0", sequence=4),
            ]
        )
        self.assertEqual(result.realized_gain, D("10.00"))
        self.assertEqual(result.open_cost_basis, D("30.00"))
        self.assertEqual(result.positions[0].lots[0].acquisition_order, 4)

    def test_sale_fees_above_proceeds_are_a_loss_with_cash_support(self):
        result = analyze(
            [
                cash(),
                trade(quantity="1", price="1", fees="0"),
                trade("SELL", "1", "1", "2", 3),
            ]
        )
        self.assertEqual(result.sales[0].net_proceeds, D("-1.00"))
        self.assertEqual(result.realized_gain, D("-2.00"))

    def test_caller_decimal_precision_does_not_change_fractional_or_large_results(self):
        events = [
            cash(amount="1000000000000"),
            trade(quantity="1234.123456", price="789.123456", fees="0.01"),
            trade("SELL", "617.061728", "800", "0.01", 3),
        ]
        with localcontext() as context:
            context.prec = 4
            result = analyze(events)
        self.assertEqual(result.sales[0].cost_basis, D("486937.89"))
        self.assertEqual(result.open_cost_basis, D("486937.89"))
        self.assertEqual(result.realized_gain, D("6711.48"))

    def test_malformed_currency_floats_and_event_shapes_are_rejected(self):
        for event in (
            replace(cash(), currency="CAD"),
            replace(trade(), quantity=1.5),
            replace(trade(), amount=D("250")),
        ):
            with self.subTest(event=event), self.assertRaises(LedgerRuleError):
                analyze([cash(), replace(event, sequence=2)])

    def test_bad_historical_balances_and_duplicate_orders_never_become_results(self):
        for events in ([trade()], [cash(), trade("SELL")], [cash(), cash()]):
            with self.subTest(events=events), self.assertRaises(LedgerRuleError):
                analyze(events)

    def test_input_is_unchanged_and_results_cannot_be_mutated(self):
        events = [trade(), cash()]
        original = list(events)
        result = analyze(events)
        self.assertEqual(events, original)
        with self.assertRaises(FrozenInstanceError):
            result.positions[0].cost_basis = D("99")
        self.assertIsInstance(result.positions[0].lots, tuple)

    def test_each_fifo_lot_conserves_cost_over_fractional_sales(self):
        for quantity, price, fees, portion in (
            ("3", "0.01", "0.01", "1"),
            ("1", "0.01", "0", "0.1"),
            ("0.000006", "10000", "0.01", "0.000001"),
        ):
            buy = trade(quantity=quantity, price=price, fees=fees)
            events = [cash(), buy]
            sold = D("0")
            sequence = 3
            while sold < D(quantity):
                amount = min(D(portion), D(quantity) - sold)
                events.append(trade("SELL", str(amount), "10000", "0", sequence))
                sold += amount
                sequence += 1
                result = analyze(events)
                allocated = sum((sale.cost_basis for sale in result.sales), D("0"))
                self.assertEqual(allocated + result.open_cost_basis, buy.gross_amount + buy.fees)
                self.assertTrue(all(sale.cost_basis >= 0 for sale in result.sales))
            self.assertEqual(result.positions, ())
