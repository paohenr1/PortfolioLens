"""One bounded, owner-scoped journal snapshot; no market-data calls or saved totals."""

from ledger.domain import LedgerRuleError
from ledger.fifo import analyze
from ledger.forms import ledger_today
from ledger.journal import effective_entries
from ledger.services import MAX_ENTRIES_PER_PORTFOLIO, private_portfolio


def journal_snapshot(user, portfolio_id):
    portfolio = private_portfolio(user, portfolio_id)
    entries = list(effective_entries(portfolio)[: MAX_ENTRIES_PER_PORTFOLIO + 1])
    if len(entries) > MAX_ENTRIES_PER_PORTFOLIO:
        raise LedgerRuleError("Journal exceeds the supported calculation limit.")
    today = ledger_today()
    for entry in entries:
        entry.as_input().validate(today)
    return portfolio, entries


def positions_snapshot(user, portfolio_id, *, as_of=None):
    portfolio, entries = journal_snapshot(user, portfolio_id)
    if as_of is not None:
        # Both cash and shares stop at the same end-of-day boundary as prices.
        entries = [entry for entry in entries if entry.event_date <= as_of]
    result = analyze([entry.as_input() for entry in entries])
    return portfolio, result, entry_labels(entries)


def entry_labels(entries):
    labels = {}
    for entry in entries:
        if entry.security_id and (
            entry.security_id not in labels
            or (entry.reference_retrieved_at, entry.recorded_at)
            > (
                labels[entry.security_id].reference_retrieved_at,
                labels[entry.security_id].recorded_at,
            )
        ):
            # Labels come from the newest stored reference, never an inferred
            # ticker history or a quote fetched while displaying calculations.
            labels[entry.security_id] = entry
    return labels
