"""Readiness descriptions, deliberately separate from future API transport."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderStatus:
    code: str
    message: str


def provider_status(*, credential_present: bool) -> ProviderStatus:
    # Having a credential is not evidence of access, entitlement, or freshness.
    if credential_present:
        return ProviderStatus(
            code="configured_unverified",
            message="Intrinio credentials are configured; data access is checked when you search.",
        )
    return ProviderStatus(
        code="not_configured",
        message="Market data unavailable: Intrinio is not configured.",
    )
