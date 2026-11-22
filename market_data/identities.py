"""Persist verified Intrinio identities alongside legacy stored IDs."""

import logging

from django.db import IntegrityError, transaction

from market_data.fields import valid_provider_id
from market_data.models import (
    CompanyIdentity,
    CompanyProviderID,
    InstrumentIdentity,
    InstrumentProviderID,
)

INTRINIO = "intrinio"
logger = logging.getLogger("research")


def _resolve_or_create(mapping, field, model, external_id):
    ids = mapping.objects.filter(provider=INTRINIO, external_id=external_id)
    target = f"{field}_id"
    existing = ids.values_list(target, flat=True).first()
    if existing is not None:
        return existing
    try:
        with transaction.atomic():
            identity = model.objects.create()
            mapping.objects.create(provider=INTRINIO, external_id=external_id, **{field: identity})
    except IntegrityError:
        # Another writer may have registered this ID. The savepoint rolls back our UUID.
        existing = ids.values_list(target, flat=True).first()
        if existing is None:
            raise
        return existing
    return identity.pk


@transaction.atomic
def register_intrinio_instrument(security_id, company_id=None):
    """Use only an exact verified security ID and its reported company ID, if present."""
    if not valid_provider_id(security_id):
        raise ValueError("Invalid Intrinio security ID.")
    if company_id is not None and not valid_provider_id(company_id):
        raise ValueError("Invalid Intrinio company ID.")
    instrument_id = _resolve_or_create(
        InstrumentProviderID, "instrument", InstrumentIdentity, security_id
    )
    if company_id is not None:
        issuer_id = _resolve_or_create(CompanyProviderID, "company", CompanyIdentity, company_id)
        instruments = InstrumentIdentity.objects.filter(pk=instrument_id)
        instruments.filter(company__isnull=True).update(company_id=issuer_id)
        if not instruments.filter(company_id=issuer_id).exists():
            # Conflicting provider metadata cannot silently reassign an established issuer.
            logger.warning("Conflicting Intrinio company link needs reconciliation")
    return instrument_id
