"""Daily index-level contracts; no ETF proxies, missing-value fill or intraday claims."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from market_data.errors import InvalidResponse

INDEX_CATALOG = {
    "sp500": ("$SPX", "ind_NX6GzO", "S&P 500"),
    "dow": ("$DJI", "ind_2zvNzA", "Dow Jones"),
    "nasdaq": ("$COMPQ", "ind_gPrpGL", "Nasdaq Composite"),
}
MAX_INDEX_OBSERVATIONS = 400


@dataclass(frozen=True)
class IndexObservation:
    date: date
    value: Decimal | None


@dataclass(frozen=True)
class IndexHistory:
    key: str
    observations: tuple[IndexObservation, ...]
    retrieved_at: datetime


def normalize_index_history(payload, key, start_date, end_date):
    if (
        not isinstance(payload, dict)
        or "next_page" not in payload
        or payload["next_page"] is not None
    ):
        raise InvalidResponse()
    symbol, identifier, _ = INDEX_CATALOG[key]
    reference = payload.get("index")
    if not isinstance(reference, dict) or (
        reference.get("id") != identifier or reference.get("symbol") != symbol
    ):
        raise InvalidResponse()
    rows = payload.get("historical_data")
    if not isinstance(rows, list) or len(rows) > MAX_INDEX_OBSERVATIONS:
        raise InvalidResponse()
    observations = {}
    for row in rows:
        if not isinstance(row, dict):
            raise InvalidResponse()
        raw_date = row.get("date")
        try:
            if not isinstance(raw_date, str) or len(raw_date) != 10:
                raise ValueError
            observed = date.fromisoformat(raw_date)
        except ValueError:
            raise InvalidResponse() from None
        if (
            observed.isoformat() != raw_date
            or not start_date <= observed <= end_date
            or observed in observations
        ):
            raise InvalidResponse()
        value = row.get("value")
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
                raise InvalidResponse()
            value = Decimal(value)
            if not value.is_finite() or not Decimal("0.00000001") <= value <= Decimal(
                "1000000000000"
            ):
                raise InvalidResponse()
        observations[observed] = IndexObservation(observed, value)
    return IndexHistory(
        key=key,
        observations=tuple(observations[d] for d in sorted(observations)),
        retrieved_at=datetime.now(UTC),
    )
