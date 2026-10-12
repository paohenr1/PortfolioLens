"""Hand-computed cash-inclusive weights and exact rounding invariants."""

import random
from dataclasses import replace
from decimal import Decimal, localcontext
from fractions import Fraction

from django.test import SimpleTestCase

from ledger.allocations import INVALID, ZERO_TOTAL, allocation_weights
from ledger.fifo import Position
from ledger.valuation import Valuation, ValuedPosition
from tests.test_valuation import AS_OF

D = Decimal


def valuation(cash="100", holdings=("100", "200")):
    rows = tuple(
        ValuedPosition(
            Position(f"sec_fixture_{index}", D("1"), D("1"), ()),
            None,
            None,
            D(value) if value is not None else None,
            None,
            None,
        )
        for index, value in enumerate(holdings)
    )
    market = None if None in holdings else sum((row.market_value for row in rows), D("0"))
    return Valuation(
        AS_OF, D(cash), D("0"), rows, market, None, D(cash) + market if market is not None else None
    )


class AllocationTests(SimpleTestCase):
    def test_cash_and_holdings_share_the_complete_total_value_basis(self):
        result = allocation_weights(valuation())
        self.assertEqual(result.total_value, D("400"))
        self.assertEqual([row.weight for row in result.rows], [D("25.00"), D("25.00"), D("50.00")])
        self.assertEqual([row.value for row in result.rows], [D("100"), D("100"), D("200")])
        self.assertIsNone(result.issue)
        self.assertEqual(result.as_of, AS_OF)

    def test_one_holding_and_zero_cash_is_one_hundred_percent(self):
        result = allocation_weights(valuation("0", ("155",)))
        self.assertEqual([row.weight for row in result.rows], [D("0.00"), D("100.00")])

    def test_cash_only_portfolio_is_one_hundred_percent(self):
        result = allocation_weights(valuation("55", ()))
        self.assertEqual(len(result.rows), 1)
        self.assertIsNone(result.rows[0].security_id)
        self.assertEqual(result.rows[0].weight, D("100.00"))

    def test_zero_total_is_undefined_for_empty_and_zero_priced_holdings(self):
        for holdings in ((), ("0",), ("0", "0")):
            result = allocation_weights(valuation("0", holdings))
            self.assertEqual(result.issue, ZERO_TOTAL)
            self.assertEqual(result.total_value, D("0"))
            self.assertTrue(all(row.weight is None for row in result.rows))

    def test_missing_position_blocks_all_weights_including_known_cash_and_position(self):
        result = allocation_weights(valuation("100", (None, "200")))
        self.assertIsNone(result.total_value)
        self.assertTrue(all(row.weight is None for row in result.rows))
        self.assertEqual([row.value for row in result.rows], [D("100"), None, D("200")])

    def test_unknown_total_blocks_weights_even_when_components_are_known(self):
        result = allocation_weights(replace(valuation(), total_value=None))
        self.assertTrue(all(row.weight is None for row in result.rows))

    def test_equal_thirds_reconcile_to_one_hundred_with_cash_first_tie(self):
        result = allocation_weights(valuation("1", ("1", "1")))
        self.assertEqual([row.weight for row in result.rows], [D("33.34"), D("33.33"), D("33.33")])

    def test_residual_goes_to_largest_remainder_and_zero_cash_never_gets_it(self):
        result = allocation_weights(valuation("0", ("1", "1", "4")))
        self.assertEqual(
            [row.weight for row in result.rows], [D("0.00"), D("16.67"), D("16.67"), D("66.66")]
        )

    def test_input_order_does_not_change_tie_breaks_or_display_order(self):
        snapshot = valuation("0", ("1", "1", "1"))
        first = allocation_weights(snapshot)
        second = allocation_weights(replace(snapshot, rows=tuple(reversed(snapshot.rows))))
        self.assertEqual(first, second)
        self.assertEqual(first.rows[1].weight, D("33.34"))

    def test_small_positive_position_can_display_zero_without_losing_its_value(self):
        result = allocation_weights(valuation("10000", ("0.01",)))
        self.assertEqual(result.rows[1].weight, D("0.00"))
        self.assertEqual(result.rows[1].value, D("0.01"))
        self.assertEqual(result.rows[0].weight, D("100.00"))

    def test_observed_zero_position_has_zero_weight_with_positive_cash(self):
        result = allocation_weights(valuation("100", ("0",)))
        self.assertEqual([row.weight for row in result.rows], [D("100.00"), D("0.00")])

    def test_decimal_context_cannot_change_percentages(self):
        snapshot = valuation("749", ("155",))
        with localcontext() as context:
            context.prec = 2
            result = allocation_weights(snapshot)
        self.assertEqual([row.weight for row in result.rows], [D("82.85"), D("17.15")])

    def test_invalid_or_unreconciled_amounts_never_become_weights(self):
        base = valuation()
        cases = [
            replace(base, cash=value)
            for value in (
                D("NaN"),
                D("Infinity"),
                D("-1"),
                100.0,
                D("0.001"),
                D("1e-10000"),
                D("1e27"),
            )
        ] + [
            replace(base, total_value=D("399")),
            replace(base, market_value=D("299")),
            replace(base, rows=base.rows * 2),
        ]
        for candidate in cases:
            with self.subTest(candidate=candidate):
                result = allocation_weights(candidate)
                self.assertEqual(result.issue, INVALID)
                self.assertTrue(all(row.weight is None for row in result.rows))

    def test_generated_cent_amounts_conserve_total_and_bound_rounding_error(self):
        rng = random.Random(20261011)
        for _ in range(200):
            cents = [rng.randrange(1000000) for _ in range(rng.randrange(1, 7))]
            if not sum(cents):
                cents[0] = 1
            amounts = [D(value).scaleb(-2) for value in cents]
            result = allocation_weights(valuation(str(amounts[0]), tuple(map(str, amounts[1:]))))
            self.assertEqual(sum(row.weight for row in result.rows), D("100.00"))
            self.assertEqual(sum(row.value for row in result.rows), result.total_value)
            for row, value in zip(result.rows, cents, strict=True):
                ideal = Fraction(value * 100, sum(cents))
                self.assertLess(abs(Fraction(row.weight) - ideal), Fraction(1, 100))
                self.assertGreaterEqual(row.weight, 0)
                self.assertLessEqual(row.weight, 100)
