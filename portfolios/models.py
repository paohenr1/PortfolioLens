"""Portfolio metadata only; positions will be derived from a future ledger."""

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
