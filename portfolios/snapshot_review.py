"""Pure dated USD snapshot values and descriptive concentration; no account returns."""

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, localcontext
from fractions import Fraction

from ledger.allocations import reconciled_percentages
from ledger.valuation import MISSING_CLOSE, confirmed_close
from market_data.fields import valid_provider_id
from market_data.venues import SUPPORTED_MICS

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
INCOMPLETE = (
    "Totals, weights and concentration are unavailable until every holding has a usable price."
)
ZERO_TOTAL = "Weights and concentration are unavailable because total value is zero."


@dataclass(frozen=True)
class ReviewHolding:
    security_id: str
    ticker: str
    exchange_mic: str
    quantity: Decimal


@dataclass(frozen=True)
class ReviewedHolding:
    holding: ReviewHolding
    raw_close: Decimal | None
    market_value: Decimal | None
    weight: Decimal | None
    retrieved_at: datetime | None
    issue: str | None


@dataclass(frozen=True)
class SnapshotReview:
    as_of: date
    cash: Decimal
    rows: tuple[ReviewedHolding, ...]
    holdings_value: Decimal | None
    total_value: Decimal | None
    cash_weight: Decimal | None
    largest_security_id: str | None
    largest_weight: Decimal | None
    top_three_weight: Decimal | None
    priced_count: int
    issue: str | None


def valid_amount(value, maximum, places, *, positive=False):
    if not isinstance(value, Decimal) or not value.is_finite():
        return False
    if value < 0 or (positive and value == 0) or value > maximum:
        return False
    if len(value.as_tuple().digits) > 32 or not -places <= value.as_tuple().exponent <= 12:
        return False
    return (Fraction(value) * 10**places).denominator == 1


def validate_inputs(as_of, cash, holdings):
    if type(as_of) is not date or not valid_amount(cash, Decimal("1000000000000"), 2):
        raise ValueError("Snapshot date or cash is invalid.")
    if len(holdings) > 5 or (not holdings and cash == 0):
        raise ValueError("Use at most five holdings, or a positive cash-only balance.")
    ids = set()
    for holding in holdings:
        if (
            not isinstance(holding, ReviewHolding)
            or not valid_provider_id(holding.security_id)
            or holding.security_id in ids
            or holding.exchange_mic not in SUPPORTED_MICS
            or not valid_amount(holding.quantity, Decimal("1000000000"), 6, positive=True)
        ):
            raise ValueError("Snapshot holdings could not be validated.")
        ids.add(holding.security_id)


def review_snapshot(as_of, cash, holdings, histories, *, issues=None):
    """Exact raw-close valuation; incomplete coverage never supplies a denominator."""
    validate_inputs(as_of, cash, holdings)
    rows = []
    with localcontext() as context:
        context.prec = 64
        for holding in sorted(holdings, key=lambda item: item.security_id):
            history = histories.get(holding.security_id)
            try:
                close = confirmed_close(history, holding.security_id, holding.exchange_mic, as_of)
            except (AttributeError, TypeError, ValueError, ArithmeticError):
                close = None
            retrieved = getattr(history, "retrieved_at", None)
            if not isinstance(retrieved, datetime) or retrieved.utcoffset() is None:
                retrieved = None
            rows.append(
                ReviewedHolding(
                    holding,
                    close,
                    (holding.quantity * close).quantize(CENT, rounding=ROUND_HALF_UP)
                    if close is not None
                    else None,
                    None,
                    retrieved,
                    (issues or {}).get(holding.security_id, MISSING_CLOSE)
                    if close is None
                    else None,
                )
            )
        priced = sum(row.market_value is not None for row in rows)
        if priced != len(rows):
            return SnapshotReview(
                as_of, cash, tuple(rows), None, None, None, None, None, None, priced, INCOMPLETE
            )
        holdings_value = sum((row.market_value for row in rows), ZERO)
        total = cash + holdings_value
        if total == 0:
            return SnapshotReview(
                as_of,
                cash,
                tuple(rows),
                holdings_value,
                total,
                None,
                None,
                None,
                None,
                priced,
                ZERO_TOTAL,
            )
        cents = [int(cash * 100)] + [int(row.market_value * 100) for row in rows]
        weights = reconciled_percentages(cents)
        rows = [replace(row, weight=weight) for row, weight in zip(rows, weights[1:], strict=True)]
        # Concentration rounds the direct cent ratio, never a sum of displayed weights.
        ranked = sorted(rows, key=lambda row: (-row.market_value, row.holding.security_id))
        largest = (
            (ranked[0].market_value / total * 100).quantize(CENT, rounding=ROUND_HALF_UP)
            if ranked
            else None
        )
        top_three = (
            (sum((row.market_value for row in ranked[:3]), ZERO) / total * 100).quantize(
                CENT, rounding=ROUND_HALF_UP
            )
            if ranked
            else None
        )
        return SnapshotReview(
            as_of,
            cash,
            tuple(rows),
            holdings_value,
            total,
            weights[0],
            ranked[0].holding.security_id if ranked else None,
            largest,
            top_three,
            priced,
            None,
        )
