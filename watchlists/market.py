"""Pure, exact-date daily observations; saved references never establish prices."""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from market_data.contracts import PriceHistory
from research.financial_math import valid_financial_number

PRICE_BASES = {"raw": "Raw close (unadjusted)", "adjusted": "Adjusted close (splits and dividends)"}
VOLUME_BASES = {"raw": "Raw volume", "adjusted": "Provider-adjusted volume"}
INSTRUMENT_ORDERS = {"added": "Date added", "ticker": "Ticker (A–Z)"}
MAX_MARKET_ITEMS = 5


@dataclass(frozen=True)
class MarketObservation:
    close: Decimal | None
    volume: Decimal | None
    price_issue: str | None
    volume_issue: str | None


def _supported(value, *, maximum, digits, exponent):
    return (
        valid_financial_number(value)
        and 0 <= value <= Decimal(maximum)
        and len(value.as_tuple().digits) <= digits
        and -18 <= value.as_tuple().exponent <= exponent
    )


def daily_observation(history: PriceHistory, security_id, market_date, price_basis, volume_basis):
    """Expose independent price/volume fields only for one confirmed daily row.

    Do not infer a change percentage, fill an earlier session, or mix bases.
    Currency/venue come from this response rather than the old saved bookmark.
    """
    if (
        not isinstance(price_basis, str)
        or price_basis not in PRICE_BASES
        or not isinstance(volume_basis, str)
        or volume_basis not in VOLUME_BASES
    ):
        raise ValueError("Choose a supported price and volume basis.")
    issue = None
    if (
        type(market_date) is not date
        or history.start_date != market_date
        or history.end_date != market_date
        or history.security.id != security_id
        or not isinstance(history.retrieved_at, datetime)
        or history.retrieved_at.tzinfo is None
        or history.retrieved_at.utcoffset() is None
        or market_date > history.retrieved_at.astimezone(UTC).date()
    ):
        issue = "The response does not confirm this exact date and instrument."
    elif history.pagination_complete is not True:
        issue = "Incomplete response; no additional page was requested."
    elif not history.observations:
        issue = "No daily observation for this exact date; no earlier date substituted."
    elif len(history.observations) != 1:
        issue = "The exact-date response must contain one unambiguous observation."
    else:
        row = history.observations[0]
        if type(row.date) is not date or row.date != market_date:
            issue = "The response does not confirm this exact date and instrument."
        elif row.intraperiod is not False:
            issue = "The daily observation is not explicitly marked complete."
    if issue:
        return MarketObservation(None, None, issue, issue)

    row = history.observations[0]
    close = row.close if price_basis == "raw" else row.adjusted_close
    volume = row.volume if volume_basis == "raw" else row.adjusted_volume
    price_issue = volume_issue = None
    if (
        not isinstance(history.security.currency, str)
        or re.fullmatch(r"[A-Z]{3}", history.security.currency) is None
        or not isinstance(history.security.exchange_mic, str)
        or not 1 <= len(history.security.exchange_mic) <= 32
        or any(ord(c) < 32 or ord(c) == 127 for c in history.security.exchange_mic)
    ):
        close = None
        price_issue = "Price-response trading currency or exchange MIC is unavailable."
    elif close is None:
        price_issue = "The selected closing-price field was not supplied."
    elif not _supported(close, maximum="1e12", digits=28, exponent=12):
        close = None
        price_issue = "The selected closing price is not a supported nonnegative number."
    if volume is None:
        volume_issue = "The selected volume field was not supplied."
    elif not _supported(volume, maximum="1e18", digits=36, exponent=18):
        volume = None
        volume_issue = "The selected volume is not a supported nonnegative share count."
    return MarketObservation(close, volume, price_issue, volume_issue)
