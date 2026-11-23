"""Local identities and provider cross-references. Neither ticker nor name is a key."""

import uuid

from django.db import models


class CompanyIdentity(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)


class InstrumentIdentity(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        CompanyIdentity,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="instruments",
    )


class CompanyProviderID(models.Model):
    company = models.ForeignKey(
        CompanyIdentity, on_delete=models.PROTECT, related_name="provider_ids"
    )
    provider = models.SlugField(max_length=32)
    external_id = models.CharField(max_length=100)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("provider", "external_id"), name="company_provider_external_unique"
            ),
            models.UniqueConstraint(
                fields=("provider", "company"), name="company_one_id_per_provider"
            ),
        ]


class InstrumentProviderID(models.Model):
    instrument = models.ForeignKey(
        InstrumentIdentity, on_delete=models.PROTECT, related_name="provider_ids"
    )
    provider = models.SlugField(max_length=32)
    external_id = models.CharField(max_length=100)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("provider", "external_id"), name="instrument_provider_external_unique"
            ),
            models.UniqueConstraint(
                fields=("provider", "instrument"), name="instrument_one_id_per_provider"
            ),
        ]
