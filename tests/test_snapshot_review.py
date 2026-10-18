"""Independent snapshot arithmetic and exact-date price acceptance examples."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext

from django.test import SimpleTestCase

from ledger.allocations import reconciled_percentages
from market_data.contracts import DailyPrice, PriceHistory, Security
from portfolios.snapshot_review import ReviewHolding, review_snapshot

D = Decimal
AS_OF = date(2020, 1, 2)
RETRIEVED = datetime(2026, 1, 5, 12, tzinfo=UTC)


def holding(identifier="a", quantity="10"):
    return ReviewHolding(identifier, "TSTF", "XNAS", D(quantity))


def history(identifier="a", close="20", *, as_of=AS_OF):
    return PriceHistory(
        Security(identifier, "TSTF", "Synthetic", "XNAS", "USD"),
        (DailyPrice(as_of, D(close) if close is not None else None, D("999"), False),),
        as_of,
        as_of,
        RETRIEVED,
        True,
    )


class SnapshotArithmeticTests(SimpleTestCase):
    def evaluate(self, *, cash="100", holdings=None, histories=None):
        return review_snapshot(
            AS_OF,
            D(cash),
            (holding(), holding("b", "5")) if holdings is None else holdings,
            {"a": history(), "b": history("b", "40")} if histories is None else histories,
        )

    def test_independent_two_holding_example_and_no_gain_or_performance_contract(self):
        result = self.evaluate()
        self.assertEqual([row.market_value for row in result.rows], [D("200.00"), D("200.00")])
        self.assertEqual(result.holdings_value, D("400.00"))
        self.assertEqual(result.total_value, D("500.00"))
        self.assertEqual(result.cash_weight, D("20.00"))
        self.assertEqual([row.weight for row in result.rows], [D("40.00"), D("40.00")])
        self.assertEqual(result.largest_security_id, "a")
        self.assertEqual(result.largest_weight, D("40.00"))
        self.assertEqual(result.top_three_weight, D("80.00"))
        self.assertEqual(result.priced_count, 2)
        self.assertIsNone(result.issue)
        for forbidden in ("cost_basis", "unrealized_gain", "realized_gain", "returns"):
            self.assertFalse(hasattr(result, forbidden))

    def test_half_cent_values_round_once_before_totals_and_weights(self):
        result = self.evaluate(
            cash="0",
            holdings=(holding("a", "0.5"), holding("b", "0.5")),
            histories={"a": history("a", "0.01"), "b": history("b", "0.01")},
        )
        self.assertEqual([row.market_value for row in result.rows], [D("0.01"), D("0.01")])
        self.assertEqual(result.total_value, D("0.02"))
        self.assertEqual([row.weight for row in result.rows], [D("50.00"), D("50.00")])

    def test_cash_first_remainder_tie_and_stable_id_order(self):
        result = self.evaluate(
            cash="1",
            holdings=(holding("b", "1"), holding("a", "1")),
            histories={"a": history("a", "1"), "b": history("b", "1")},
        )
        self.assertEqual(result.cash_weight, D("33.34"))
        self.assertEqual([row.holding.security_id for row in result.rows], ["a", "b"])
        self.assertEqual([row.weight for row in result.rows], [D("33.33"), D("33.33")])
        self.assertEqual(result.top_three_weight, D("66.67"))
        self.assertEqual(result.cash_weight + sum(row.weight for row in result.rows), D("100.00"))

    def test_concentration_uses_direct_values_not_rounded_weights(self):
        result = self.evaluate(
            cash="2",
            holdings=tuple(holding(key, "1") for key in ("d", "c", "b", "a")),
            histories={key: history(key, "1") for key in "abcd"},
        )
        self.assertEqual(result.largest_security_id, "a")
        self.assertEqual(result.largest_weight, D("16.67"))
        self.assertEqual(sum(row.weight for row in result.rows[:3]), D("50.01"))
        self.assertEqual(result.top_three_weight, D("50.00"))
        self.assertEqual(result.cash_weight + sum(row.weight for row in result.rows), D("100.00"))
        result = self.evaluate(
            cash="0",
            holdings=tuple(holding(key, "1") for key in "abc"),
            histories={key: history(key, "1") for key in "abc"},
        )
        self.assertEqual(result.rows[0].weight, D("33.34"))
        self.assertEqual(result.largest_weight, D("33.33"))

    def test_missing_price_withholds_aggregates_but_preserves_known_values(
        self,
    ):
        result = self.evaluate(histories={"a": history()})
        self.assertEqual(result.cash, D("100"))
        self.assertEqual(result.rows[0].market_value, D("200.00"))
        self.assertIsNone(result.rows[1].market_value)
        self.assertEqual(result.priced_count, 1)
        for field in (
            "total_value",
            "holdings_value",
            "cash_weight",
            "largest_weight",
            "top_three_weight",
        ):
            self.assertIsNone(getattr(result, field))
        self.assertTrue(all(row.weight is None for row in result.rows))
        self.assertTrue(result.issue)

    def test_cash_only_zero_and_tiny_values_are_distinct(self):
        result = self.evaluate(cash="0.01", holdings=(), histories={})
        self.assertEqual(result.holdings_value, D("0.00"))
        self.assertEqual(result.total_value, D("0.01"))
        self.assertEqual(result.cash_weight, D("100.00"))
        self.assertIsNone(result.largest_weight)
        self.assertIsNone(result.top_three_weight)
        for cash in ("0", "1"):
            result = self.evaluate(
                cash=cash, holdings=(holding(),), histories={"a": history(close="0")}
            )
            self.assertEqual(result.priced_count, 1)
            self.assertEqual(result.total_value, D(cash))
            self.assertEqual(result.rows[0].raw_close, D("0"))
            self.assertEqual(result.rows[0].weight, None if cash == "0" else D("0.00"))
            self.assertEqual(result.largest_weight, None if cash == "0" else D("0.00"))
        result = self.evaluate(
            cash="1",
            holdings=(holding("a", "0.000001"),),
            histories={"a": history(close="0.000001")},
        )
        self.assertEqual(result.rows[0].raw_close, D("0.000001"))
        self.assertEqual(result.rows[0].market_value, D("0.00"))
        self.assertEqual(result.rows[0].weight, D("0.00"))

    def test_context_independence_and_maximum_values(self):
        holdings = tuple(holding(key, "1000000000") for key in "abcde")
        histories = {key: history(key, "1000000000000") for key in "abcde"}
        with localcontext() as context:
            context.prec = 4
            result = self.evaluate(cash="1000000000000", holdings=holdings, histories=histories)
        self.assertEqual(result.holdings_value, D("5000000000000000000000.00"))
        self.assertEqual(result.total_value, D("5000000001000000000000.00"))
        self.assertEqual(result.largest_weight, D("20.00"))
        self.assertEqual(result.top_three_weight, D("60.00"))

    def test_price_identity_date_currency_mic_basis_completion_and_timestamp_fail_closed(self):
        quote = history()
        variants = [
            replace(quote, security=replace(quote.security, id="other")),
            replace(quote, security=replace(quote.security, currency="EUR")),
            replace(quote, security=replace(quote.security, exchange_mic="XNYS")),
            replace(quote, start_date=AS_OF - timedelta(days=1)),
            replace(quote, end_date=AS_OF + timedelta(days=1)),
            replace(quote, pagination_complete=False),
            replace(quote, retrieved_at=RETRIEVED.replace(tzinfo=None)),
            replace(quote, retrieved_at=None),
            replace(quote, observations=()),
            replace(quote, observations=quote.observations * 2),
            history(as_of=AS_OF - timedelta(days=1)),
            history(close=None),
            None,
        ]
        for changes in (
            {"date": AS_OF + timedelta(days=1)},
            {"intraperiod": True},
            {"intraperiod": None},
            *(
                {"close": value}
                for value in (D("-1"), D("NaN"), D("Infinity"), D("1e-19"), D("1000000000001"), 1.0)
            ),
        ):
            variants.append(
                replace(quote, observations=(replace(quote.observations[0], **changes),))
            )
        for candidate in variants:
            with self.subTest(candidate=candidate):
                result = self.evaluate(holdings=(holding(),), histories={"a": candidate})
                self.assertIsNone(result.rows[0].raw_close)
                self.assertIsNone(result.total_value)
                self.assertEqual(result.priced_count, 0)

    def test_invalid_input_contract_fails_before_calculation(self):
        for cash, holdings in (
            (D("0"), ()),
            (D("-1"), (holding(),)),
            (D("1.001"), (holding(),)),
            (D("NaN"), (holding(),)),
            (1.0, (holding(),)),
            (D("1"), (holding(),) * 2),
            (D("1"), tuple(holding(str(i)) for i in range(6))),
            (D("1"), (replace(holding(), quantity=D("0")),)),
            (D("1"), (replace(holding(), quantity=D("0.0000001")),)),
            (D("1"), (replace(holding(), exchange_mic="XTST"),)),
        ):
            with self.subTest(cash=cash, holdings=holdings), self.assertRaises(ValueError):
                review_snapshot(AS_OF, cash, holdings, {})

    def test_shared_allocation_helper_rejects_invalid_cent_contract(self):
        for values in ([], [0, 0], [-1, 2], [True, 1], [D("1"), 1]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                reconciled_percentages(values)
        self.assertEqual(
            reconciled_percentages([100, 100, 100]), (D("33.34"), D("33.33"), D("33.33"))
        )
