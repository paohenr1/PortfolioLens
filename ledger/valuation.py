"""Pure USD valuation of an already date-scoped FIFO snapshot; no I/O."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, localcontext

from ledger.domain import CENT, ZERO
from ledger.fifo import Position
from market_data.contracts import PriceHistory

MISSING_CLOSE = "No confirmed raw USD close matching this date and instrument."


@dataclass(frozen=True)
class ValuedPosition:
    position: Position
    raw_close: Decimal | None
    retrieved_at: datetime | None
    market_value: Decimal | None
    unrealized_gain: Decimal | None
    issue: str | None


@dataclass(frozen=True)
class Valuation:
    as_of: date
    cash: Decimal
    open_cost_basis: Decimal
    rows: tuple[ValuedPosition, ...]
    market_value: Decimal | None
    unrealized_gain: Decimal | None
    total_value: Decimal | None


def confirmed_close(history, security_id, exchange_mic, as_of):
    if not isinstance(history, PriceHistory) or (
        history.security.id != security_id
        or history.security.currency != "USD"
        or not exchange_mic
        or history.security.exchange_mic != exchange_mic
        or history.start_date != as_of
        or history.end_date != as_of
        or history.pagination_complete is not True
        or len(history.observations) != 1
        or history.retrieved_at.tzinfo is None
        or history.retrieved_at.utcoffset() is None
    ):
        return None
    observation = history.observations[0]
    close = observation.close
    if (
        observation.date != as_of
        or observation.intraperiod is not False
        or not isinstance(close, Decimal)
        or not close.is_finite()
        or not ZERO <= close <= Decimal("1000000000000")
        or len(close.as_tuple().digits) > 28
        or not -18 <= close.as_tuple().exponent <= 12
    ):
        return None
    # Adjusted close is deliberately ignored: recorded shares already incorporate
    # recorded splits, and dividends enter cash. Adjusting again would double count.
    return close


def value_snapshot(analysis, as_of, histories, exchange_mics, *, issues=None):
    """Round each position once; totals sum those cents so displayed rows reconcile.

    The caller must scope journal events through as_of before building analysis.
    Missing quotes remain None; known zero prices and cash-only holdings are valid.
    """
    rows = []
    with localcontext() as context:
        context.prec = 64
        for position in analysis.positions:
            history = histories.get(position.security_id)
            close = confirmed_close(
                history, position.security_id, exchange_mics.get(position.security_id), as_of
            )
            market_value = (
                (position.quantity * close).quantize(CENT, rounding=ROUND_HALF_UP)
                if close is not None
                else None
            )
            rows.append(
                ValuedPosition(
                    position,
                    close,
                    history.retrieved_at if close is not None else None,
                    market_value,
                    market_value - position.cost_basis if market_value is not None else None,
                    (issues or {}).get(position.security_id, MISSING_CLOSE)
                    if close is None
                    else None,
                )
            )
        complete = all(row.market_value is not None for row in rows)
        market_value = (
            sum((row.market_value for row in rows), ZERO).quantize(CENT) if complete else None
        )
        return Valuation(
            as_of,
            analysis.cash,
            analysis.open_cost_basis,
            tuple(rows),
            market_value,
            market_value - analysis.open_cost_basis if complete else None,
            analysis.cash + market_value if complete else None,
        )
