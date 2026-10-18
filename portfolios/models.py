"""Transaction portfolio metadata and separate supplied holdings snapshots."""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower, Trim


class Portfolio(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    name = models.CharField(max_length=100)
    # Reporting denomination is explicit. Cross-currency valuation waits for FX policy.
    reporting_currency = models.CharField(max_length=3, default="USD", editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "id")
        indexes = [models.Index(fields=("owner", "-created_at"), name="portfolio_owner_created")]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(name__regex=r"\S"), name="portfolio_name_nonblank"
            ),
            models.CheckConstraint(
                condition=models.Q(reporting_currency="USD"), name="portfolio_usd_only"
            ),
            models.UniqueConstraint(
                Lower(Trim("name")), models.F("owner"), name="portfolio_owner_name_unique"
            ),
        ]

    def clean(self):
        super().clean()
        self.name = self.name.strip()
        if not self.name or any(
            ord(character) < 32 or ord(character) == 127 for character in self.name
        ):
            raise ValidationError({"name": "Enter a portfolio name without control characters."})


class HoldingsSnapshot(models.Model):
    """Confirmed supplied inputs; deliberately unrelated to the transaction ledger."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    name = models.CharField(max_length=100)
    as_of = models.DateField()
    cash = models.DecimalField(max_digits=15, decimal_places=2)
    currency = models.CharField(max_length=3, default="USD", editable=False)
    confirmation_version = models.PositiveSmallIntegerField(default=1, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "id")
        indexes = [models.Index(fields=("owner", "-created_at"), name="snapshot_owner_created")]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(name__regex=r"\S"), name="snapshot_name_nonblank"
            ),
            models.CheckConstraint(condition=models.Q(currency="USD"), name="snapshot_usd_only"),
            models.CheckConstraint(
                condition=models.Q(cash__gte=0, cash__lte=1000000000000), name="snapshot_cash_range"
            ),
            models.CheckConstraint(
                condition=models.Q(confirmation_version=1), name="snapshot_confirmation_v1"
            ),
        ]


class SnapshotHolding(models.Model):
    snapshot = models.ForeignKey(
        HoldingsSnapshot, on_delete=models.CASCADE, related_name="holdings"
    )
    security_id = models.CharField(max_length=100)
    ticker = models.CharField(max_length=32)
    exchange_mic = models.CharField(max_length=16)
    quantity = models.DecimalField(max_digits=16, decimal_places=6)
    currency = models.CharField(max_length=3, default="USD", editable=False)
    name = models.CharField(max_length=512, blank=True)
    reference_retrieved_at = models.DateTimeField()

    class Meta:
        ordering = ("security_id",)
        constraints = [
            models.UniqueConstraint(
                fields=("snapshot", "security_id"), name="snapshot_instrument_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0, quantity__lte=1000000000),
                name="snapshot_quantity_range",
            ),
            models.CheckConstraint(
                condition=models.Q(currency="USD"), name="snapshot_holding_usd_only"
            ),
        ]


class SnapshotSubmission(models.Model):
    """Retry identity; deletion retains only this receipt until its preview expires."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    key = models.UUIDField()
    digest = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    snapshot = models.OneToOneField(HoldingsSnapshot, null=True, on_delete=models.SET_NULL)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("owner", "key"), name="snapshot_owner_submission_unique"
            )
        ]
