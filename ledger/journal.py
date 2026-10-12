"""The current interpretation excludes superseded entries in one SQL snapshot."""

import hashlib

from ledger.models import Correction, Entry


def effective_entries(portfolio):
    # Replacement and audit link commit together. A single statement cannot see
    # a replacement from one commit and the original's status from another.
    return Entry.objects.filter(portfolio=portfolio).exclude(
        pk__in=Correction.objects.filter(portfolio=portfolio).values("target_id")
    )


def fingerprint(entries):
    # Entry contents are immutable, so identities fully identify this interpretation.
    return hashlib.sha256("|".join(str(entry.pk) for entry in entries).encode()).hexdigest()
