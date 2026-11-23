"""Calculate one exact-date portfolio valuation on opening the overview."""

from datetime import timedelta
from hashlib import sha256
from threading import Lock

import exchange_calendars
from django.conf import settings
from django.core.cache.backends.locmem import LocMemCache

from ledger.analytics import entry_labels, journal_snapshot
from ledger.fifo import analyze
from ledger.forms import ledger_today
from ledger.valuation_services import ValuationLimitError, load_valuation
from research.services import MAX_AUTOMATIC_PRICE_REQUESTS

# Local, bounded reuse of complete valuations when provider terms permit retention.
_results = LocMemCache("automatic-portfolio-values", {"OPTIONS": {"MAX_ENTRIES": 256}})
_inflight_lock = Lock()
_inflight = set()
_CACHE_SECONDS = 300


def automatic_valuation(user, portfolio_id, client_address):
    _, entries = journal_snapshot(user, portfolio_id)
    end = ledger_today() - timedelta(days=1)
    start = end - timedelta(days=10)
    calendar = exchange_calendars.get_calendar("XNYS", start=start, end=end + timedelta(days=7))
    as_of = calendar.sessions_in_range(start, end)[-1].date()
    entries = [entry for entry in entries if entry.event_date <= as_of]
    analysis = analyze([entry.as_input() for entry in entries])
    labels = entry_labels(entries)
    if len(analysis.positions) > MAX_AUTOMATIC_PRICE_REQUESTS:
        raise ValuationLimitError("Use manual valuation for more than two holdings.")
    if not analysis.positions:
        valuation, error = load_valuation(analysis, labels, as_of, client_address)
        return valuation, error, False

    # Journal entries are immutable. A correction changes the effective entry IDs.
    identity = ":".join(
        [str(user.pk), str(portfolio_id), as_of.isoformat(), *(str(e.pk) for e in entries)]
    )
    key = sha256(identity.encode()).hexdigest()
    with _inflight_lock:
        if settings.PORTFOLIO_VALUATION_CACHE:
            cached = _results.get(key)
            if cached is not None:
                return cached, None, False
        if key in _inflight:
            return None, None, True
        _inflight.add(key)
    try:
        valuation, error = load_valuation(analysis, labels, as_of, client_address, background=True)
        if settings.PORTFOLIO_VALUATION_CACHE and valuation.total_value is not None:
            _results.set(key, valuation, timeout=_CACHE_SECONDS)
        return valuation, error, False
    finally:
        with _inflight_lock:
            _inflight.remove(key)
