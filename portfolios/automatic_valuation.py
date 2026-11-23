"""Compute the dated value and opted-in return using one private journal snapshot."""

from dataclasses import dataclass
from datetime import date, timedelta
from hashlib import sha256
from threading import Lock

import exchange_calendars
from django.conf import settings
from django.core.cache.backends.locmem import LocMemCache

from ledger.analytics import entry_labels, journal_snapshot
from ledger.fifo import analyze
from ledger.forms import ledger_today
from ledger.performance import Performance, PerformanceRuleError
from ledger.performance_services import performance_plan, value_performance_plan
from ledger.valuation import Valuation
from ledger.valuation_services import load_valuation
from market_data.errors import ProviderError
from research.services import MAX_AUTOMATIC_PRICE_REQUESTS

# Local, bounded reuse of complete results when provider terms permit retention.
_results = LocMemCache("automatic-portfolio-values", {"OPTIONS": {"MAX_ENTRIES": 256}})
_inflight_lock = Lock()
_inflight = set()
_CACHE_SECONDS = 300


@dataclass
class AutomaticOverview:
    valuation: Valuation | None = None
    performance: Performance | None = None
    period: tuple[date, date] | None = None
    valuation_issue: str = ""
    performance_issue: str = ""
    provider_error: ProviderError | None = None
    busy: bool = False


def _latest_session(day):
    start = day - timedelta(days=10)
    calendar = exchange_calendars.get_calendar("XNYS", start=start, end=day + timedelta(days=7))
    return calendar.date_to_session(day, direction="previous").date()


def _automatic_performance(result, entries, valuation_requests, client_address):
    if result.period is None:
        return
    try:
        plan = performance_plan(entries, *result.period)
        valued_date = result.valuation.as_of if result.valuation is not None else None
        remaining_requests = sum(
            len(point.analysis.positions) for point in plan if point.as_of != valued_date
        )
        if remaining_requests + valuation_requests > MAX_AUTOMATIC_PRICE_REQUESTS:
            raise PerformanceRuleError("This period needs manual performance analysis.")
        performance, _, error = value_performance_plan(
            plan,
            entries,
            client_address,
            background=True,
            existing_valuation=result.valuation,
            error=result.provider_error,
        )
    except PerformanceRuleError as error:
        result.performance_issue = str(error)
    else:
        result.performance = performance
        result.provider_error = error


def automatic_valuation(user, portfolio_id, client_address, dates):
    portfolio, entries = journal_snapshot(user, portfolio_id)
    as_of = _latest_session(ledger_today() - timedelta(days=1))
    closing_entries = [entry for entry in entries if entry.event_date <= as_of]
    analysis = analyze([entry.as_input() for entry in closing_entries])
    labels = entry_labels(closing_entries)
    result = AutomaticOverview()
    valuation_requests = len(analysis.positions)
    if valuation_requests > MAX_AUTOMATIC_PRICE_REQUESTS:
        result.valuation_issue = "Use manual valuation for more than two holdings."
        valuation_requests = 0
    if portfolio.automatic_performance_enabled:
        end = dates.get("end_date", as_of)
        start = dates.get("start_date") or _latest_session(end - timedelta(days=30))
        result.period = (start, end)

    # Journal entries are immutable. A correction changes the effective entry IDs.
    # Include the analysis period and entries through both requested end dates.
    scope_end = max(as_of, result.period[1]) if result.period else as_of
    identity = ":".join(
        [
            str(user.pk),
            str(portfolio_id),
            as_of.isoformat(),
            str(result.period),
            *(str(entry.pk) for entry in entries if entry.event_date <= scope_end),
        ]
    )
    key = sha256(identity.encode()).hexdigest()
    with _inflight_lock:
        if settings.PORTFOLIO_VALUATION_CACHE:
            cached = _results.get(key)
            if cached is not None:
                return cached
        if key in _inflight:
            result.busy = True
            return result
        _inflight.add(key)
    try:
        if not result.valuation_issue:
            result.valuation, result.provider_error = load_valuation(
                analysis, labels, as_of, client_address, background=True
            )
        _automatic_performance(result, entries, valuation_requests, client_address)
        if (
            settings.PORTFOLIO_VALUATION_CACHE
            and result.provider_error is None
            and result.valuation is not None
            and result.valuation.total_value is not None
            and (
                not result.period
                or (result.performance and result.performance.return_percent is not None)
            )
        ):
            _results.set(key, result, timeout=_CACHE_SECONDS)
        return result
    finally:
        with _inflight_lock:
            _inflight.remove(key)
