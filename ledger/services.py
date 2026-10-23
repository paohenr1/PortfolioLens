"""Atomic, owner-scoped appends with replay and idempotent retries."""

import logging
import uuid
from dataclasses import replace

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max

from ledger.domain import REFERENCED, LedgerRuleError
from ledger.fifo import analyze
from ledger.forms import ledger_today
from ledger.journal import effective_entries
from ledger.models import Correction, Entry
from market_data.errors import InvalidResponse, ProviderError
from market_data.fields import valid_provider_id
from market_data.venues import SUPPORTED_MICS
from portfolios.services import owned_portfolios
from research import services as market_data

MAX_ENTRIES_PER_PORTFOLIO = 1000

logger = logging.getLogger("research")


class PortfolioUnavailable(Exception):
    pass


def private_portfolio(user, portfolio_id, *, lock=False):
    queryset = owned_portfolios(user)
    if lock:
        queryset = queryset.select_for_update(of=("self",))
    portfolio = queryset.filter(pk=portfolio_id, owner__is_active=True).first()
    if portfolio is None:
        raise PortfolioUnavailable
    return portfolio


def retry_entry(portfolio, client_key, intent, *, auto_sequence=False):
    if Correction.objects.filter(portfolio=portfolio, client_key=client_key).exists():
        raise LedgerRuleError("This submission key belongs to a correction. Open a new form.")
    existing = Entry.objects.filter(portfolio=portfolio, client_key=client_key).first()
    if existing and existing.is_replacement:
        raise LedgerRuleError("This submission key belongs to a correction. Open a new form.")
    if existing and auto_sequence:
        intent = replace(intent, sequence=existing.sequence)
    if existing and existing.as_input() != intent:
        raise LedgerRuleError(
            "This submission key already records different details. "
            "Open a new form for a new transaction."
        )
    return existing


def assigned_order(portfolio, intent):
    """Include voided/replaced slots; never silently reuse an old journal position."""
    last = (
        Entry.objects.filter(portfolio=portfolio, event_date=intent.event_date).aggregate(
            last=Max("sequence")
        )["last"]
        or 0
    )
    if last >= 999999:
        raise LedgerRuleError("This date has reached the supported transaction limit.")
    return replace(intent, sequence=last + 1)


def next_revision(portfolio, intent):
    previous = Entry.objects.filter(
        portfolio=portfolio, event_date=intent.event_date, sequence=intent.sequence
    ).aggregate(last=Max("revision"))["last"]
    return 0 if previous is None else previous + 1


def make_entry(portfolio, client_key, intent, reference, *, is_replacement=False):
    entry = Entry(
        portfolio=portfolio,
        client_key=client_key,
        kind=intent.kind,
        event_date=intent.event_date,
        sequence=intent.sequence,
        security_id=intent.security_id,
        quantity=intent.quantity,
        unit_price=intent.unit_price,
        amount=intent.gross_amount,
        fees=intent.fees,
        split_new=intent.split_new,
        split_old=intent.split_old,
        revision=next_revision(portfolio, intent),
        is_replacement=is_replacement,
        **reference,
    )
    entry.full_clean(validate_unique=False, validate_constraints=False)
    entry.save()
    return entry


def validate_append(entries, intent):
    if len(entries) >= MAX_ENTRIES_PER_PORTFOLIO:
        raise LedgerRuleError("This portfolio has reached the 1,000-entry development limit.")
    # Full FIFO validation also checks exact split conversion for each open lot.
    return analyze([entry.as_input() for entry in entries] + [intent])


def security_reference(intent, address):
    if intent.kind not in REFERENCED:
        return {}
    try:
        result = market_data.security_details(intent.security_id, address)
    except ProviderError:
        raise
    except Exception:
        # Provider exception details may contain authenticated URLs.
        logger.error("Unexpected ledger security-reference failure")
        raise ProviderError() from None
    security = result.security
    if security.id != intent.security_id:
        raise InvalidResponse()
    if (
        security.currency != "USD"
        or security.exchange_mic not in SUPPORTED_MICS
        or not security.ticker
    ):
        raise LedgerRuleError(
            "Instrument entries require a verified USD security on a supported U.S. listing venue, "
            "with a ticker and MIC."
        )
    return {
        "security_ticker": security.ticker,
        "exchange_mic": security.exchange_mic,
        "reference_retrieved_at": result.retrieved_at,
    }


def append_entry(*, user, portfolio_id, client_key, intent, client_address, auto_sequence=False):
    """Network verification occurs outside the lock; all ledger checks repeat inside it."""
    try:
        if not isinstance(client_key, uuid.UUID):
            raise LedgerRuleError("A valid submission key is required.")
        intent.validate(ledger_today())
        if intent.security_id and not valid_provider_id(intent.security_id):
            raise LedgerRuleError("Enter a valid provider security ID.")
        portfolio = private_portfolio(user, portfolio_id)
        existing = retry_entry(portfolio, client_key, intent, auto_sequence=auto_sequence)
        if existing:
            return existing
        if auto_sequence:
            intent = assigned_order(portfolio, intent)
        try:
            entries = list(effective_entries(portfolio))
            if Entry.objects.filter(portfolio=portfolio).count() >= MAX_ENTRIES_PER_PORTFOLIO:
                raise LedgerRuleError(
                    "This portfolio has reached the 1,000-entry development limit."
                )
            validate_append(entries, intent)
        except LedgerRuleError:
            # An identical request can commit after the first duplicate check
            # but before this unlocked snapshot. Its committed event can make
            # preflight fail (notably split order/replay). Recheck the key before
            # rejecting it; the locked path still validates every new append.
            existing = retry_entry(portfolio, client_key, intent, auto_sequence=auto_sequence)
            if existing:
                return existing
            raise
        reference = security_reference(intent, client_address)
        with transaction.atomic():
            portfolio = private_portfolio(user, portfolio_id, lock=True)
            existing = retry_entry(portfolio, client_key, intent, auto_sequence=auto_sequence)
            if existing:
                return existing
            if auto_sequence:
                intent = assigned_order(portfolio, intent)
            entries = list(effective_entries(portfolio))
            if Entry.objects.filter(portfolio=portfolio).count() >= MAX_ENTRIES_PER_PORTFOLIO:
                raise LedgerRuleError(
                    "This portfolio has reached the 1,000-entry development limit."
                )
            validate_append(entries, intent)
            if intent.kind in REFERENCED and any(
                entry.security_id == intent.security_id
                and entry.exchange_mic != reference["exchange_mic"]
                for entry in entries
            ):
                raise LedgerRuleError(
                    "This security's listing venue changed. "
                    "Reference reconciliation is required before more trades."
                )
            return make_entry(portfolio, client_key, intent, reference)
    except LedgerRuleError as error:
        raise ValidationError({"__all__": str(error)}) from None
