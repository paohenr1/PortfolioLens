"""Owner-scoped, bounded mutations with provider I/O outside database locks."""

import logging
from datetime import datetime

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models.functions import Lower
from django.utils.timezone import is_aware

from market_data.errors import InvalidResponse, ProviderError
from market_data.fields import optional_boolean, optional_text, valid_provider_id
from research import services as market_data
from watchlists.market import INSTRUMENT_ORDERS, PRICE_BASES, VOLUME_BASES
from watchlists.models import Watchlist, WatchlistItem

MAX_WATCHLISTS_PER_USER = 50
MAX_ITEMS_PER_WATCHLIST = 100
logger = logging.getLogger("research")


class WatchlistStorageUnavailable(Exception):
    pass


class WatchlistUnavailable(Exception):
    pass


def owned_watchlists(user):
    if connection.vendor != "postgresql":
        raise WatchlistStorageUnavailable
    if not user.is_authenticated or not user.is_active:
        raise PermissionDenied
    return Watchlist.objects.filter(owner=user, owner__is_active=True)


def private_watchlist(user, watchlist_id, *, lock=False):
    queryset = owned_watchlists(user)
    if lock:
        queryset = queryset.select_for_update(of=("self",))
    watchlist = queryset.filter(pk=watchlist_id).first()
    if watchlist is None:
        raise WatchlistUnavailable
    return watchlist


def create_watchlist(*, user, name):
    owned_watchlists(user)
    watchlist = Watchlist(owner=user, name=name)
    watchlist.full_clean(validate_constraints=False)
    try:
        with transaction.atomic():
            # Serialize creations for this owner, including differently named lists.
            owner = user.__class__.objects.select_for_update().filter(pk=user.pk, is_active=True)
            if owner.first() is None:
                raise PermissionDenied
            if owned_watchlists(user).count() >= MAX_WATCHLISTS_PER_USER:
                raise ValidationError("An account can have up to 50 watchlists.")
            watchlist.save(force_insert=True)
    except IntegrityError as error:
        diagnostic = getattr(error.__cause__, "diag", None)
        if diagnostic and diagnostic.constraint_name == "watchlist_owner_name_unique":
            raise ValidationError(
                {"name": "You already have a watchlist with this name."}
            ) from None
        raise
    return watchlist


def existing_or_capacity(watchlist, security_id):
    existing = watchlist.items.filter(security_id=security_id).first()
    if existing:
        return existing
    if watchlist.items.count() >= MAX_ITEMS_PER_WATCHLIST:
        raise ValidationError("A watchlist can contain up to 100 instruments.")
    return None


def reference_fields(security_id, address):
    try:
        result = market_data.security_details(security_id, address)
        security = result.security
        if security.id != security_id or not isinstance(result.retrieved_at, datetime):
            raise InvalidResponse()
        if not is_aware(result.retrieved_at):
            raise InvalidResponse()
        fields = {
            field: optional_text(vars(security), field, limit=limit)
            for field, limit in (
                ("ticker", 32),
                ("name", 512),
                ("exchange_mic", 16),
                ("currency", 3),
            )
        }
        fields.update(
            active=optional_boolean(vars(security), "active"),
            delisted=optional_boolean(vars(security), "delisted"),
            reference_retrieved_at=result.retrieved_at,
        )
        return fields
    except ProviderError:
        raise
    except Exception:
        # Exception details can contain authenticated URLs; log only the operation.
        logger.error("Unexpected watchlist security-reference failure")
        raise ProviderError() from None


def add_instrument(*, user, watchlist_id, security_id, client_address):
    watchlist = private_watchlist(user, watchlist_id)
    if not valid_provider_id(security_id):
        raise ValidationError({"security_id": "Enter a valid provider instrument ID."})
    existing = existing_or_capacity(watchlist, security_id)
    if existing:
        return existing
    fields = reference_fields(security_id, client_address)
    with transaction.atomic():
        # Recheck authorization, uniqueness and allowance after network verification.
        watchlist = private_watchlist(user, watchlist_id, lock=True)
        existing = existing_or_capacity(watchlist, security_id)
        if existing:
            return existing
        return WatchlistItem.objects.create(watchlist=watchlist, security_id=security_id, **fields)


def private_item(user, watchlist_id, item_id):
    watchlist = private_watchlist(user, watchlist_id)
    item = watchlist.items.filter(pk=item_id).first()
    if item is None:
        raise WatchlistUnavailable
    return watchlist, item


def remove_instrument(*, user, watchlist_id, item_id):
    with transaction.atomic():
        watchlist = private_watchlist(user, watchlist_id, lock=True)
        item = watchlist.items.filter(pk=item_id).first()
        if item is None:
            raise WatchlistUnavailable
        item.delete()


def ordered_items(watchlist):
    if watchlist.instrument_order == "ticker":
        return watchlist.items.order_by(Lower("ticker").asc(nulls_last=True), "added_at", "id")
    return watchlist.items.all()


def save_preferences(*, user, watchlist_id, price_basis, volume_basis, instrument_order):
    # Authorization precedes input validation, keeping foreign/missing IDs uniform.
    private_watchlist(user, watchlist_id)
    for field, value, choices in (
        ("price_basis", price_basis, PRICE_BASES),
        ("volume_basis", volume_basis, VOLUME_BASES),
        ("instrument_order", instrument_order, INSTRUMENT_ORDERS),
    ):
        if not isinstance(value, str) or value not in choices:
            raise ValidationError({field: "Choose a supported preference."})
    with transaction.atomic():
        watchlist = private_watchlist(user, watchlist_id, lock=True)
        watchlist.price_basis = price_basis
        watchlist.volume_basis = volume_basis
        watchlist.instrument_order = instrument_order
        watchlist.save(update_fields=("price_basis", "volume_basis", "instrument_order"))
    return watchlist
