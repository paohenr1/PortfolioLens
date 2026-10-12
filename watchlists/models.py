"""Private instrument bookmarks; reference snapshots never stand in for quotes."""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower, Trim

from watchlists.market import INSTRUMENT_ORDERS, PRICE_BASES, VOLUME_BASES


class Watchlist(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    price_basis = models.CharField(max_length=8, choices=tuple(PRICE_BASES.items()), default="raw")
    volume_basis = models.CharField(
        max_length=8, choices=tuple(VOLUME_BASES.items()), default="raw"
    )
    instrument_order = models.CharField(
        max_length=8, choices=tuple(INSTRUMENT_ORDERS.items()), default="added"
    )

    class Meta:
        ordering = ("-created_at", "id")
        indexes = [models.Index(fields=("owner", "-created_at"), name="watchlist_owner_created")]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(price_basis__in=tuple(PRICE_BASES)),
                name="watchlist_price_basis_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(volume_basis__in=tuple(VOLUME_BASES)),
                name="watchlist_volume_basis_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(instrument_order__in=tuple(INSTRUMENT_ORDERS)),
                name="watchlist_order_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(name__regex=r"\S"), name="watchlist_name_nonblank"
            ),
            models.UniqueConstraint(
                Lower(Trim("name")), models.F("owner"), name="watchlist_owner_name_unique"
            ),
        ]

    def clean(self):
        super().clean()
        self.name = self.name.strip()
        if not self.name or any(ord(c) < 32 or ord(c) == 127 for c in self.name):
            raise ValidationError({"name": "Enter a watchlist name without control characters."})


class WatchlistItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    watchlist = models.ForeignKey(Watchlist, on_delete=models.CASCADE, related_name="items")
    security_id = models.CharField(max_length=100)
    ticker = models.CharField(max_length=32, null=True)
    name = models.CharField(max_length=512, null=True)
    exchange_mic = models.CharField(max_length=16, null=True)
    currency = models.CharField(max_length=3, null=True)
    active = models.BooleanField(null=True)
    delisted = models.BooleanField(null=True)
    reference_retrieved_at = models.DateTimeField()
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("added_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("watchlist", "security_id"), name="watchlist_instrument_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(security_id__regex=r"^[A-Za-z0-9_-]{1,100}$"),
                name="watchlist_security_id_valid",
            ),
        ]
