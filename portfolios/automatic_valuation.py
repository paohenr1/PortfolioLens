"""Compute the dated value and opted-in return using one private journal snapshot."""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
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
from market_data.errors import InvalidResponse, ProviderError, ProviderRateLimited
from research.services import MAX_AUTOMATIC_PRICE_REQUESTS

# Local, bounded reuse of complete results when provider terms permit retention.
_results = LocMemCache("automatic-portfolio-values", {"OPTIONS": {"MAX_ENTRIES": 256}})
_verified = LocMemCache("automatic-portfolio-verified", {"OPTIONS": {"MAX_ENTRIES": 256}})
_inflight_lock = Lock()
_inflight = set()
_CACHE_SECONDS = 300
_VERIFIED_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class VerifiedFigure:
    amount: Decimal
    end_date: date
    start_date: date | None = None


@dataclass
class AutomaticOverview:
    valuation: Valuation | None = None
    performance: Performance | None = None
    period: tuple[date, date] | None = None
    valuation_issue: str = ""
    performance_issue: str = ""
    provider_error: ProviderError | None = None
    busy: bool = False
    stale_valuation: VerifiedFigure | None = None
    stale_performance: VerifiedFigure | None = None


def _latest_session(day):
    start = day - timedelta(days=10)
    calendar = exchange_calendars.get_calendar("XNYS", start=start, end=day + timedelta(days=7))
    return calendar.date_to_session(day, direction="previous").date()


def _automatic_performance(result, entries, valuation_requests, client_address, failures):
    if result.period is None:
        return False
    try:
        plan = performance_plan(entries, *result.period)
        valued_date = result.valuation.as_of if result.valuation is not None else None
        remaining_requests = sum(
            len(point.analysis.positions) for point in plan if point.as_of != valued_date
        )
        if remaining_requests + valuation_requests > MAX_AUTOMATIC_PRICE_REQUESTS:
            raise PerformanceRuleError("This period needs manual performance analysis.")
        performance, boundaries, error = value_performance_plan(
            plan,
            entries,
            client_address,
            background=True,
            existing_valuation=result.valuation,
            error=result.provider_error,
            failures=failures,
        )
    except PerformanceRuleError as error:
        result.performance_issue = str(error)
        return False
    else:
        result.performance = performance
        result.provider_error = error
        return any(valuation.total_value is None for valuation in boundaries)


def _key(owner_id, portfolio_id, metric, selection, entries):
    identity = ":".join(
        [str(owner_id), str(portfolio_id), metric, str(selection), *(str(e.pk) for e in entries)]
    )
    return sha256(identity.encode()).hexdigest()


def _allows_fallback(error):
    return type(error) is ProviderError or isinstance(error, (ProviderRateLimited, InvalidResponse))


def _verified_figure(key, figure, *, requested_end, allow_fallback):
    # Requests on either side of a closing-date change can finish out of order.
    with _inflight_lock:
        previous = _verified.get(key)
        if figure is not None:
            if previous is None or figure.end_date >= previous.end_date:
                _verified.set(key, figure, timeout=_VERIFIED_SECONDS)
        elif allow_fallback and previous is not None and previous.end_date <= requested_end:
            return previous
    return None


def _apply_verified_results(
    result, portfolio, closing_entries, entries, dates, as_of, failures, missing_performance
):
    # The response's leading error is for status and retry handling. A denial
    # anywhere in the price load also makes previously retained figures unusable.
    allow_fallback = all(_allows_fallback(error) for error in failures)
    if result.valuation is not None:
        total = result.valuation.total_value
        amount = VerifiedFigure(total, as_of) if total is not None else None
        key = _key(portfolio.owner_id, portfolio.pk, "value", None, closing_entries)
        result.stale_valuation = _verified_figure(
            key, amount, requested_end=as_of, allow_fallback=allow_fallback
        )
    if result.performance is not None:
        performance = result.performance
        value = performance.return_percent
        amount = (
            VerifiedFigure(value, performance.end_date, performance.start_date)
            if value is not None
            else None
        )
        selection = (dates.get("start_date"), dates.get("end_date"))
        scoped_entries = [entry for entry in entries if entry.event_date <= performance.end_date]
        key = _key(portfolio.owner_id, portfolio.pk, "return", selection, scoped_entries)
        result.stale_performance = _verified_figure(
            key,
            amount,
            requested_end=performance.end_date,
            allow_fallback=missing_performance and allow_fallback,
        )


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
    key = _key(
        user.pk,
        portfolio_id,
        "fresh",
        (as_of, result.period, dates.get("start_date"), dates.get("end_date")),
        [entry for entry in entries if entry.event_date <= scope_end],
    )
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
        failures = []
        if not result.valuation_issue:
            result.valuation, result.provider_error = load_valuation(
                analysis, labels, as_of, client_address, background=True, failures=failures
            )
        missing_performance = _automatic_performance(
            result, entries, valuation_requests, client_address, failures
        )
        if settings.PORTFOLIO_VALUATION_CACHE:
            _apply_verified_results(
                result,
                portfolio,
                closing_entries,
                entries,
                dates,
                as_of,
                failures,
                missing_performance,
            )
        if result.stale_valuation or result.stale_performance:
            current, current_entries = journal_snapshot(user, portfolio_id)
            if result.stale_valuation and closing_entries != [
                entry for entry in current_entries if entry.event_date <= as_of
            ]:
                result.stale_valuation = None
            if result.stale_performance:
                end = result.period[1]
                if not current.automatic_performance_enabled or [
                    entry for entry in entries if entry.event_date <= end
                ] != [entry for entry in current_entries if entry.event_date <= end]:
                    result.stale_performance = None
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
