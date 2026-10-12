"""Preview and commit restatements; an audit decision is never a cash-flow event."""

import uuid

from django.db import transaction

from ledger.domain import REFERENCED, LedgerRuleError
from ledger.fifo import analyze
from ledger.forms import ledger_today
from ledger.journal import effective_entries, fingerprint
from ledger.models import Correction, Entry
from ledger.services import (
    MAX_ENTRIES_PER_PORTFOLIO,
    PortfolioUnavailable,
    make_entry,
    private_portfolio,
    security_reference,
)
from market_data.fields import valid_provider_id

MAX_CORRECTIONS_PER_PORTFOLIO = 1000


def private_target(user, portfolio_id, target_id):
    portfolio = private_portfolio(user, portfolio_id)
    target = Entry.objects.filter(portfolio=portfolio, pk=target_id).first()
    if target is None:
        raise PortfolioUnavailable
    return portfolio, target


def validate_reason(reason):
    if not isinstance(reason, str):
        raise LedgerRuleError("Enter a reason for the correction.")
    reason = reason.strip()
    if not reason or len(reason) > 500 or any(ord(c) < 32 or ord(c) == 127 for c in reason):
        raise LedgerRuleError("Enter a reason of up to 500 characters without control characters.")
    return reason


def retry_correction(portfolio, client_key, target_id, intent, reason):
    correction = (
        Correction.objects.filter(portfolio=portfolio, client_key=client_key)
        .select_related("replacement")
        .first()
    )
    if correction:
        recorded_intent = correction.replacement.as_input() if correction.replacement else None
        if (
            correction.target_id != target_id
            or recorded_intent != intent
            or correction.reason != reason
        ):
            raise LedgerRuleError(
                "This submission key already records different correction details."
            )
        return correction
    if Entry.objects.filter(portfolio=portfolio, client_key=client_key).exists():
        raise LedgerRuleError("This submission key already belongs to a transaction.")
    return None


def checked_preview(portfolio, target, intent):
    entries = list(effective_entries(portfolio)[: MAX_ENTRIES_PER_PORTFOLIO + 1])
    if len(entries) > MAX_ENTRIES_PER_PORTFOLIO:
        raise LedgerRuleError("Journal exceeds the supported calculation limit.")
    if not any(entry.pk == target.pk for entry in entries):
        raise LedgerRuleError(
            "This entry has already been corrected. Select its current replacement."
        )
    if Correction.objects.filter(portfolio=portfolio).count() >= MAX_CORRECTIONS_PER_PORTFOLIO:
        raise LedgerRuleError("This portfolio has reached the 1,000-correction development limit.")
    if intent is not None:
        intent.validate(ledger_today())
        if intent.security_id and not valid_provider_id(intent.security_id):
            raise LedgerRuleError("Enter a valid provider security ID.")
        if intent == target.as_input():
            raise LedgerRuleError("The replacement must change transaction details.")
        if Entry.objects.filter(portfolio=portfolio).count() >= MAX_ENTRIES_PER_PORTFOLIO:
            raise LedgerRuleError("This portfolio has reached the 1,000-entry development limit.")
    original = [entry.as_input() for entry in entries]
    updated = [entry.as_input() for entry in entries if entry.pk != target.pk]
    if intent is not None:
        updated.append(intent)
    # Validate every prefix and lot, including later sells, dividends and splits.
    before, after = analyze(original), analyze(updated)
    return before, after, fingerprint(entries), entries


def preview_correction(*, user, portfolio_id, target_id, intent, reason):
    validate_reason(reason)
    portfolio, target = private_target(user, portfolio_id, target_id)
    before, after, version, _ = checked_preview(portfolio, target, intent)
    return portfolio, target, before, after, version


def commit_correction(
    *, user, portfolio_id, target_id, intent, reason, client_key, expected_version, client_address
):
    reason = validate_reason(reason)
    if not isinstance(client_key, uuid.UUID):
        raise LedgerRuleError("A valid correction submission key is required.")
    portfolio, target = private_target(user, portfolio_id, target_id)
    existing = retry_correction(portfolio, client_key, target_id, intent, reason)
    if existing:
        return existing
    try:
        _, _, version, _ = checked_preview(portfolio, target, intent)
        if version != expected_version:
            raise LedgerRuleError(
                "The journal changed after this preview. Preview the correction again."
            )
    except LedgerRuleError:
        # An identical request can commit between the initial retry lookup and
        # this read. Recover its result instead of treating our own retry as stale.
        existing = retry_correction(portfolio, client_key, target_id, intent, reason)
        if existing:
            return existing
        raise
    reference = security_reference(intent, client_address) if intent is not None else {}
    with transaction.atomic():
        portfolio = private_portfolio(user, portfolio_id, lock=True)
        existing = retry_correction(portfolio, client_key, target_id, intent, reason)
        if existing:
            return existing
        _, _, version, entries = checked_preview(portfolio, target, intent)
        if version != expected_version:
            raise LedgerRuleError(
                "The journal changed after this preview. Preview the correction again."
            )
        if (
            intent is not None
            and intent.kind in REFERENCED
            and any(
                entry.pk != target.pk
                and entry.security_id == intent.security_id
                and entry.exchange_mic != reference["exchange_mic"]
                for entry in entries
            )
        ):
            raise LedgerRuleError(
                "This security's listing venue changed. Reference reconciliation is required."
            )
        replacement = (
            make_entry(portfolio, client_key, intent, reference, is_replacement=True)
            if intent
            else None
        )
        correction = Correction(
            portfolio=portfolio,
            target=target,
            replacement=replacement,
            reason=reason,
            client_key=client_key,
        )
        correction.full_clean(validate_unique=False, validate_constraints=False)
        correction.save()
        return correction
