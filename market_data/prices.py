"""Daily price validation, independent of web forms and provider transport."""

import re
from datetime import UTC, date, datetime
from decimal import Decimal

from market_data.contracts import DailyPrice
from market_data.errors import InvalidResponse

MAX_PRICE_DAYS = 366
PRICE_PAGE_SIZE = 100
MAX_PRICE_PAGES = 4
MIN_PRICE_DATE = date(1900, 1, 1)


def validate_price_range(start_date: date, end_date: date):
    # The inclusive limit permits a leap-year window without unbounded history.
    if type(start_date) is not date or type(end_date) is not date:
        raise ValueError("Use calendar dates for price history.")
    if start_date < MIN_PRICE_DATE or start_date > end_date:
        raise ValueError("Start date must be on or after 1900-01-01 and before the end date.")
    if end_date > datetime.now(UTC).date():
        raise ValueError("End date cannot be in the future.")
    if (end_date - start_date).days + 1 > MAX_PRICE_DAYS:
        raise ValueError("Choose a date range of at most 366 days, including both dates.")


def _price(value: object) -> Decimal | None:
    if value is None:
        return None
    # JSON numbers stay Decimal; strings and booleans are not observed prices.
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise InvalidResponse()
    number = Decimal(value)
    if not number.is_finite() or number < 0 or number > Decimal("1e12"):
        raise InvalidResponse()
    # Bound both chart arithmetic and fixed-point HTML expansion of hostile exponents.
    if not -18 <= number.as_tuple().exponent <= 12 or len(number.as_tuple().digits) > 28:
        raise InvalidResponse()
    return number


def normalize_daily_price(payload: object, start_date: date, end_date: date) -> DailyPrice:
    if not isinstance(payload, dict) or payload.get("frequency") != "daily":
        raise InvalidResponse()
    raw_date = payload.get("date")
    if not isinstance(raw_date, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_date) is None:
        raise InvalidResponse()
    try:
        observation_date = date.fromisoformat(raw_date)
    except ValueError:
        raise InvalidResponse() from None
    if not start_date <= observation_date <= end_date:
        raise InvalidResponse()
    intraperiod = payload.get("intraperiod")
    if intraperiod is not None and not isinstance(intraperiod, bool):
        raise InvalidResponse()
    return DailyPrice(
        date=observation_date,
        close=_price(payload.get("close")),
        adjusted_close=_price(payload.get("adj_close")),
        intraperiod=intraperiod,
        volume=_volume(payload.get("volume")),
        adjusted_volume=_volume(payload.get("adj_volume")),
    )


def _volume(value: object) -> Decimal | None:
    # Intrinio documents both volume fields as numbers, not integer-only counts.
    # Keep fractional observations exact; never truncate an adjusted share count.
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise InvalidResponse()
    number = Decimal(value)
    if (
        not number.is_finite()
        or not 0 <= number <= Decimal("1e18")
        or not -18 <= number.as_tuple().exponent <= 18
        or len(number.as_tuple().digits) > 36
    ):
        raise InvalidResponse()
    return number
