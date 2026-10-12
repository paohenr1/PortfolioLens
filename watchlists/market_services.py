"""Owner-checked bounded reads; never hold database locks during provider I/O."""

import logging
from dataclasses import dataclass
from uuid import UUID

from django.core.exceptions import ValidationError

from market_data.errors import ProviderError, ProviderRateLimited
from market_data.prices import validate_price_range
from research import services as market_data
from research.fundamentals import financial_text
from watchlists import services
from watchlists.market import MAX_MARKET_ITEMS, PRICE_BASES, VOLUME_BASES, daily_observation

logger = logging.getLogger("research")


@dataclass(frozen=True)
class MarketRow:
    item: object
    history: object | None = None
    observation: object | None = None
    error: ProviderError | None = None
    not_requested: bool = False

    @property
    def close_text(self):
        return financial_text(self.observation.close if self.observation else None)

    @property
    def volume_text(self):
        return financial_text(self.observation.volume if self.observation else None)


def load_market_information(
    *, user, watchlist_id, item_ids, market_date, price_basis, volume_basis, client_address
):
    watchlist = services.private_watchlist(user, watchlist_id)
    if (
        not isinstance(item_ids, (list, tuple))
        or not 1 <= len(item_ids) <= MAX_MARKET_ITEMS
        or any(not isinstance(item_id, UUID) for item_id in item_ids)
        or len(set(item_ids)) != len(item_ids)
    ):
        raise ValidationError("Choose one to five different instruments per load.")
    if (
        not isinstance(price_basis, str)
        or price_basis not in PRICE_BASES
        or not isinstance(volume_basis, str)
        or volume_basis not in VOLUME_BASES
    ):
        raise ValidationError("Choose supported price and volume bases.")
    try:
        validate_price_range(market_date, market_date)
    except ValueError as error:
        raise ValidationError(str(error)) from None
    items = tuple(services.ordered_items(watchlist).filter(pk__in=item_ids))
    if len(items) != len(item_ids):
        raise services.WatchlistUnavailable
    rows, rate_limit = [], None
    for item in items:
        if rate_limit is not None:
            rows.append(MarketRow(item, not_requested=True))
            continue
        try:
            history = market_data.daily_prices(item.security_id, market_date, client_address)
            observation = daily_observation(
                history, item.security_id, market_date, price_basis, volume_basis
            )
            rows.append(MarketRow(item, history, observation))
        except ProviderError as error:
            rows.append(MarketRow(item, error=error))
            if isinstance(error, ProviderRateLimited):
                rate_limit = error
        except Exception:
            # Do not log unexpected exception details or authenticated URLs.
            logger.error("Unexpected watchlist daily-information failure")
            rows.append(MarketRow(item, error=ProviderError()))
    # A removal, ownership change or deactivation during network I/O must not
    # leave a stale authorized response. Reads never update saved snapshots.
    current = services.private_watchlist(user, watchlist_id)
    if current.items.filter(pk__in=item_ids).count() != len(item_ids):
        raise services.WatchlistUnavailable
    return tuple(rows), rate_limit
