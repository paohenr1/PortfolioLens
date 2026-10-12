"""Hand-calculated cash/share cases independent of Django persistence."""

from datetime import date
from decimal import Decimal, localcontext

from django.test import SimpleTestCase

from ledger.domain import EventInput, LedgerRuleError, replay

D = Decimal
DAY = date(2020, 1, 2)


def cash(kind="DEPOSIT", amount="1000", sequence=1, event_date=DAY):
    return EventInput(kind, event_date, sequence, amount=D(amount))


def trade(
    kind="BUY",
    quantity="10",
    price="25",
    fees="1",
    sequence=2,
    event_date=DAY,
    security_id="sec_fixture_primary",
):
    return EventInput(kind, event_date, sequence, security_id, D(quantity), D(price), fees=D(fees))


class LedgerDomainTests(SimpleTestCase):
    def test_deposit_buy_partial_sell_withdrawal_and_fee_reconcile(self):
        events = [
            cash(),
            trade(),
            trade("SELL", "4", "30", "2", 3),
            cash("WITHDRAWAL", "100", 4),
            cash("FEE", "3", 5),
        ]
        for event in events:
            event.validate(DAY)
        result = replay(events)
        self.assertEqual(result.cash, D("764.00"))
        self.assertEqual(result.quantities, {"sec_fixture_primary": D("6")})

    def test_cash_contributions_are_not_a_return_calculation(self):
        self.assertEqual(replay([cash(amount="500")]).cash, D("500.00"))
        self.assertEqual(replay([]).cash, D("0.00"))

    def test_fractional_quantity_exact_cash_and_half_up_cent_rounding(self):
        event = trade(quantity="0.5", price="0.01", fees="0")
        self.assertEqual(event.gross_amount, D("0.01"))
        self.assertEqual(replay([cash(amount="0.01"), event]).cash, D("0.00"))
        self.assertEqual(
            replay([cash(amount="1"), trade(quantity="0.1", price="0.2", fees="0")]).cash, D("0.98")
        )

    def test_arithmetic_is_independent_of_callers_decimal_precision(self):
        with localcontext() as context:
            context.prec = 4
            result = replay(
                [
                    cash(amount="123456789.12"),
                    trade(quantity="1234.123456", price="789.123456", fees="0.01"),
                ]
            )
        self.assertEqual(result.cash, D("122482913.34"))

    def test_sell_fees_above_proceeds_consume_cash(self):
        result = replay(
            [
                cash(amount="10"),
                trade(quantity="1", price="1", fees="0"),
                trade("SELL", "1", "1", "2", 3),
            ]
        )
        self.assertEqual(result.cash, D("8.00"))
        self.assertEqual(result.quantities["sec_fixture_primary"], D("0"))

    def test_negative_cash_prefix_is_rejected_despite_later_deposit(self):
        with self.assertRaisesMessage(LedgerRuleError, "cash negative"):
            replay([cash("WITHDRAWAL", "1", 1), cash(amount="1000", sequence=2)])

    def test_short_position_prefix_is_rejected_despite_later_buy(self):
        with self.assertRaisesMessage(LedgerRuleError, "short position"):
            replay([cash(), trade("SELL", sequence=2), trade(sequence=3)])

    def test_share_identity_uses_security_id_not_ticker(self):
        with self.assertRaisesMessage(LedgerRuleError, "short position"):
            replay([cash(), trade(security_id="one"), trade("SELL", security_id="two", sequence=3)])

    def test_explicit_order_is_unique_and_input_order_is_not_authoritative(self):
        self.assertEqual(replay([trade(), cash()]).cash, D("749.00"))
        with self.assertRaisesMessage(LedgerRuleError, "already used"):
            replay([cash(), cash(amount="10")])

    def test_dates_kind_and_order_are_bounded(self):
        for event in (
            cash(event_date=date(1899, 1, 1)),
            cash(event_date=date(2021, 1, 1)),
            cash(sequence=0),
            cash(sequence=True),
            cash(sequence=1000000),
            cash(kind="DIVIDEND"),
        ):
            with self.subTest(event=event):
                with self.assertRaises(LedgerRuleError):
                    event.validate(DAY)

    def test_numeric_values_are_positive_finite_bounded_and_never_floats(self):
        for value in (
            D("-1"),
            D("0"),
            D("NaN"),
            D("Infinity"),
            D("0.001"),
            D("1000000000001"),
            1.1,
        ):
            with self.subTest(value=value):
                with self.assertRaises(LedgerRuleError):
                    EventInput("DEPOSIT", DAY, 1, amount=value).validate(DAY)
        for event in (
            trade(quantity="0.0000001"),
            trade(price="0.0000001"),
            trade(fees="-1"),
            trade(quantity="0.000001", price="0.000001"),
        ):
            with self.assertRaises(LedgerRuleError):
                event.validate(DAY)

    def test_event_shapes_reject_ambiguous_cash_or_trade_inputs(self):
        for event in (
            EventInput("BUY", DAY, 1, "id", D("1"), D("2"), amount=D("2")),
            EventInput("DEPOSIT", DAY, 1, "id", amount=D("2")),
            EventInput("FEE", DAY, 1, amount=D("2"), fees=D("1")),
        ):
            with self.assertRaises(LedgerRuleError):
                event.validate(DAY)
