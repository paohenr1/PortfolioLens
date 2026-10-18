"""Pure allocation percentages from one complete USD valuation; no new I/O."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext
from fractions import Fraction

from ledger.valuation import Valuation

BASIS_POINTS = 10000  # One basis point is 0.01 percentage points.
INCOMPLETE = "Allocation weights are unavailable until every position has a usable price."
ZERO_TOTAL = "Allocation weights are unavailable because total value is zero."
INVALID = "Allocation weights are unavailable because valuation amounts could not be reconciled."


@dataclass(frozen=True)
class AllocationRow:
    security_id: str | None  # None identifies cash, never a ticker or provider ID.
    value: Decimal | None
    weight: Decimal | None


@dataclass(frozen=True)
class Allocation:
    as_of: date
    total_value: Decimal | None
    rows: tuple[AllocationRow, ...]
    issue: str | None


def _cents(value):
    if (
        not isinstance(value, Decimal)
        or not value.is_finite()
        or value < 0
        or value > Decimal("1e26")
        or value.as_tuple().exponent < -18
        or len(value.as_tuple().digits) > 40
    ):
        return None
    # Fraction keeps cent validation independent of the caller's Decimal context.
    cents = Fraction(value) * 100
    return cents.numerator if cents.denominator == 1 else None


def allocation_weights(valuation: Valuation) -> Allocation:
    """Include cash; display cash first then stable IDs, with exact 100.00% totals.

    Use largest remainders in integer basis points. Independent rounding can give
    99.99% or 100.01%; distributing residual points preserves the displayed total.
    Equal remainders use cash first, then stable ID order, never input/query order.
    """
    components = [(None, valuation.cash)] + [
        (row.position.security_id, row.market_value)
        for row in sorted(valuation.rows, key=lambda row: row.position.security_id)
    ]

    def unavailable(issue, *, total=None):
        return Allocation(
            valuation.as_of,
            total,
            tuple(AllocationRow(identifier, value, None) for identifier, value in components),
            issue,
        )

    if valuation.total_value is None or any(value is None for _, value in components):
        # Known cash/individual prices do not establish any portfolio denominator.
        return unavailable(INCOMPLETE)
    values = [_cents(value) for _, value in components]
    total, market = _cents(valuation.total_value), _cents(valuation.market_value)
    identifiers = [identifier for identifier, _ in components]
    if (
        None in values
        or total is None
        or market is None
        or len(identifiers) != len(set(identifiers))
        or sum(values) != total
        or sum(values[1:]) != market
    ):
        return unavailable(INVALID)
    if total == 0:
        return unavailable(ZERO_TOTAL, total=valuation.total_value)

    weights = reconciled_percentages(values)
    return Allocation(
        valuation.as_of,
        valuation.total_value,
        tuple(
            AllocationRow(identifier, value, weight)
            for (identifier, value), weight in zip(components, weights, strict=True)
        ),
        None,
    )


def reconciled_percentages(values):
    """Apportion 100.00% from nonnegative integer cents in caller-defined tie order."""
    if not values or any(type(value) is not int or value < 0 for value in values):
        raise ValueError("Allocation requires nonnegative integer cents.")
    total = sum(values)
    if total <= 0:
        raise ValueError("Allocation requires positive total value.")
    divisions = [divmod(value * BASIS_POINTS, total) for value in values]
    points = [floor for floor, _ in divisions]
    residual = BASIS_POINTS - sum(points)
    ranked = sorted(range(len(points)), key=lambda index: (-divisions[index][1], index))
    for index in ranked[:residual]:
        points[index] += 1
    with localcontext() as context:
        context.prec = 64
        return tuple(Decimal(point).scaleb(-2) for point in points)
