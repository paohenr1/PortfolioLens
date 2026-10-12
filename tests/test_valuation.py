"""Independent dollar examples and conservative date/identity validity checks."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal, localcontext

from django.test import SimpleTestCase

from ledger.domain import EventInput
from ledger.fifo import analyze
from ledger.valuation import value_snapshot
from market_data.contracts import DailyPrice, PriceHistory
from tests.test_ledger import REFERENCE
from tests.test_ledger_domain import cash, trade

D = Decimal
AS_OF = date(2020, 1, 8)
IDENTIFIER = "sec_fixture_primary"


def history(close="15.5", *, identifier=IDENTIFIER, as_of=AS_OF):
    return PriceHistory(
        replace(REFERENCE.security, id=identifier),
        (DailyPrice(as_of, D(close) if close is not None else None, D("999"), False),),
        as_of,
        as_of,
        datetime(2026, 10, 10, 12, tzinfo=UTC),
        True,
    )


class ValuationTests(SimpleTestCase):
    def evaluate(self, analysis=None, quotes=None):
        return value_snapshot(
            analysis or analyze([cash(), trade()]),
            AS_OF,
            quotes if quotes is not None else {IDENTIFIER: history()},
            {IDENTIFIER: "XNYS", "sec_fixture_other": "XNYS"},
        )

    def test_raw_close_fee_basis_and_recorded_cash_reconcile(self):
        result = self.evaluate()
        self.assertEqual(result.rows[0].raw_close, D("15.5"))
        self.assertEqual(result.market_value, D("155.00"))
        self.assertEqual(result.unrealized_gain, D("-96.00"))
        self.assertEqual(result.cash, D("749.00"))
        self.assertEqual(result.total_value, D("904.00"))

    def test_partial_sale_retains_fifo_cost_not_realized_gain(self):
        result = self.evaluate(analyze([cash(), trade(), trade("SELL", "4", "30", "2", 3)]))
        self.assertEqual(result.market_value, D("93.00"))
        self.assertEqual(result.open_cost_basis, D("150.60"))
        self.assertEqual(result.unrealized_gain, D("-57.60"))
        self.assertEqual(result.total_value, D("960.00"))

    def test_recorded_split_and_net_dividend_are_not_adjusted_twice(self):
        events = [
            cash(),
            trade(),
            EventInput("SPLIT", date(2020, 1, 3), 1, IDENTIFIER, split_new=2, split_old=1),
            EventInput("DIVIDEND", date(2020, 1, 4), 1, IDENTIFIER, amount=D("7")),
        ]
        result = self.evaluate(analyze(events))
        self.assertEqual(result.market_value, D("310.00"))
        self.assertEqual(result.unrealized_gain, D("59.00"))
        self.assertEqual(result.cash, D("756.00"))
        self.assertEqual(result.total_value, D("1066.00"))

    def test_missing_quote_is_unknown_not_zero(self):
        result = self.evaluate(quotes={})
        self.assertIsNone(result.rows[0].market_value)
        self.assertIsNone(result.rows[0].unrealized_gain)
        self.assertIsNone(result.total_value)
        self.assertEqual(result.cash, D("749.00"))
        self.assertEqual(result.open_cost_basis, D("251.00"))

    def test_adjusted_close_never_fills_missing_raw_close(self):
        result = self.evaluate(quotes={IDENTIFIER: history(None)})
        self.assertIsNone(result.market_value)
        self.assertIsNone(result.unrealized_gain)

    def test_known_zero_price_is_a_valid_observation(self):
        result = self.evaluate(quotes={IDENTIFIER: history("0")})
        self.assertEqual(result.market_value, D("0.00"))
        self.assertEqual(result.unrealized_gain, D("-251.00"))
        self.assertEqual(result.total_value, D("749.00"))

    def test_cash_only_portfolio_needs_no_quotes(self):
        result = self.evaluate(analyze([cash(amount="55")]), {})
        self.assertEqual(result.rows, ())
        self.assertEqual(result.market_value, D("0.00"))
        self.assertEqual(result.unrealized_gain, D("0.00"))
        self.assertEqual(result.total_value, D("55.00"))

    def test_incomplete_position_keeps_known_rows_but_all_totals_unknown(self):
        analysis = analyze([cash(), trade(), trade(sequence=3, security_id="sec_fixture_other")])
        result = self.evaluate(analysis)
        self.assertIsNone(result.market_value)
        self.assertIsNone(result.unrealized_gain)
        self.assertIsNone(result.total_value)
        self.assertEqual([row.market_value for row in result.rows], [None, D("155.00")])

    def test_half_cent_rounding_per_position_and_total_reconciliation(self):
        analysis = analyze(
            [
                cash(),
                trade(quantity="0.5", price="0.01", fees="0"),
                trade(
                    quantity="0.5",
                    price="0.01",
                    fees="0",
                    sequence=3,
                    security_id="sec_fixture_other",
                ),
            ]
        )
        result = self.evaluate(
            analysis,
            {
                IDENTIFIER: history("0.01"),
                "sec_fixture_other": history("0.01", identifier="sec_fixture_other"),
            },
        )
        self.assertEqual([row.market_value for row in result.rows], [D("0.01"), D("0.01")])
        self.assertEqual(result.market_value, D("0.02"))
        self.assertEqual(result.unrealized_gain, D("0.00"))
        self.assertEqual(result.total_value, D("1000.00"))

    def test_callers_decimal_precision_cannot_change_valuation(self):
        analysis = analyze([cash(), trade()])
        with localcontext() as context:
            context.prec = 2
            result = self.evaluate(analysis)
        self.assertEqual(result.market_value, D("155.00"))
        self.assertEqual(result.total_value, D("904.00"))

    def test_wrong_identity_currency_venue_range_cursor_or_timestamp_is_unavailable(self):
        base = history()
        for candidate in (
            replace(base, security=replace(base.security, id="sec_wrong")),
            replace(base, security=replace(base.security, currency="EUR")),
            replace(base, security=replace(base.security, currency=None)),
            replace(base, security=replace(base.security, exchange_mic="XNAS")),
            replace(base, security=replace(base.security, exchange_mic=None)),
            replace(base, start_date=date(2020, 1, 7)),
            replace(base, end_date=date(2020, 1, 9)),
            replace(base, pagination_complete=False),
            replace(base, retrieved_at=base.retrieved_at.replace(tzinfo=None)),
            replace(base, observations=()),
            replace(base, observations=base.observations * 2),
        ):
            with self.subTest(candidate=candidate):
                self.assertIsNone(self.evaluate(quotes={IDENTIFIER: candidate}).market_value)

    def test_old_future_unconfirmed_or_invalid_close_is_unavailable(self):
        base = history()
        observation = base.observations[0]
        for changed in (
            replace(observation, date=date(2020, 1, 7)),
            replace(observation, date=date(2020, 1, 9)),
            replace(observation, intraperiod=True),
            replace(observation, intraperiod=None),
            *(
                replace(observation, close=close)
                for close in (
                    None,
                    D("NaN"),
                    D("Infinity"),
                    D("-1"),
                    D("1000000000001"),
                    15.5,
                    D("1e-19"),
                    D("0.12345678901234567890123456789"),
                )
            ),
        ):
            with self.subTest(observation=changed):
                candidate = replace(base, observations=(changed,))
                self.assertIsNone(self.evaluate(quotes={IDENTIFIER: candidate}).market_value)
