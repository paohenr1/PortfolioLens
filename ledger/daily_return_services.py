"""One corrected journal snapshot; at most two bounded historical price loads."""

import logging
from dataclasses import replace

from ledger.analytics import entry_labels, journal_snapshot
from ledger.benchmarks import calculate_comparison, unavailable_comparison
from ledger.daily_returns import build_daily_plan, calculate_daily_returns
from ledger.performance import PerformanceRuleError
from ledger.services import SUPPORTED_MICS
from ledger.valuation import value_snapshot
from market_data.contracts import PriceHistory
from market_data.errors import ProviderError, ProviderRateLimited
from research import services as market_data

MAX_SERIES_INSTRUMENTS = 2
logger = logging.getLogger("research")


def _daily_histories(histories, day, start, end):
    result = {}
    for identifier, history in histories.items():
        # Never turn a truncated or mismatched history into a complete daily
        # quote. Duplicate dates fail closed, including at unused dates.
        if (
            not isinstance(history, PriceHistory)
            or history.start_date != start
            or history.end_date != end
            or history.pagination_complete is not True
            or len(history.observations) > 90
            or any(not start <= point.date <= end for point in history.observations)
            or len({point.date for point in history.observations}) != len(history.observations)
        ):
            continue
        result[identifier] = replace(
            history,
            start_date=day,
            end_date=day,
            observations=tuple(point for point in history.observations if point.date == day),
        )
    return result


def load_daily_returns(user, portfolio_id, start, end, client_address):
    return _load_daily_returns(user, portfolio_id, start, end, client_address)[:4]


def load_daily_comparison(user, portfolio_id, start, end, client_address, benchmark_id):
    return _load_daily_returns(user, portfolio_id, start, end, client_address, benchmark_id)


def _load_daily_returns(user, portfolio_id, start, end, client_address, benchmark_id=""):
    portfolio, entries = journal_snapshot(user, portfolio_id)
    boundaries = build_daily_plan([entry.as_input() for entry in entries], start, end)
    identifiers = sorted(
        {position.security_id for point in boundaries for position in point.analysis.positions}
    )
    if len(identifiers) > MAX_SERIES_INSTRUMENTS:
        raise PerformanceRuleError(
            "Daily returns support at most two instruments held across this period, "
            "including holdings sold before its end. Choose a smaller period."
        )
    labels = [
        entry_labels([entry for entry in entries if entry.event_date <= point.as_of])
        for point in boundaries
    ]
    histories, issues, error = {}, {}, None
    for identifier in identifiers:
        venues = {
            label[identifier].exchange_mic
            for label, point in zip(labels, boundaries, strict=True)
            if any(p.security_id == identifier for p in point.analysis.positions)
        }
        if len(venues) != 1 or not venues.issubset(SUPPORTED_MICS):
            issues[identifier] = "A consistent supported U.S. equity venue is required."
            continue
        if isinstance(error, ProviderRateLimited):
            issues[identifier] = error.message
            continue
        try:
            # Each load has at most four pages; two instruments bound the action
            # to eight requests, and every page also spends the shared budget.
            histories[identifier] = market_data.historical_prices(
                identifier, start, end, client_address
            )
        except ProviderError as failure:
            issues[identifier] = failure.message
            if error is None or isinstance(failure, ProviderRateLimited):
                error = failure
        except Exception:
            logger.error("Unexpected portfolio daily history failure")
            issues[identifier] = ProviderError.message
            error = error or ProviderError()
    valuations = tuple(
        value_snapshot(
            point.analysis,
            point.as_of,
            _daily_histories(histories, point.as_of, start, end),
            {identifier: entry.exchange_mic for identifier, entry in label.items()},
            issues=issues,
        )
        for point, label in zip(boundaries, labels, strict=True)
    )
    series = calculate_daily_returns(boundaries, valuations)
    comparison = None
    if benchmark_id:
        comparison, failure = _load_benchmark(
            series, benchmark_id, histories, start, end, client_address, error
        )
        if failure and (error is None or isinstance(failure, ProviderRateLimited)):
            error = failure
    return portfolio, series, valuations, error, comparison


def _load_benchmark(series, identifier, histories, start, end, client_address, error):
    # Preflight and all portfolio prices use the same materialized journal.
    # A rate limit stops the action, including optional benchmark requests.
    if isinstance(error, ProviderRateLimited):
        return unavailable_comparison(identifier, error.message), None
    try:
        reference = market_data.security_details(identifier, client_address)
        security = reference.security
        if (
            security.id != identifier
            or security.currency != "USD"
            or security.exchange_mic not in SUPPORTED_MICS
        ):
            return unavailable_comparison(
                identifier, "Choose a USD security on a supported U.S. equity venue."
            ), None
        # Reuse an already loaded same-instrument history. Otherwise a single
        # page is enough for the bounded window; a remaining cursor fails closed.
        history = histories.get(identifier)
        if history is None:
            history = market_data.benchmark_prices(identifier, start, end, client_address)
        return calculate_comparison(series, reference, history, identifier), None
    except ProviderError as failure:
        return unavailable_comparison(identifier, failure.message), failure
    except Exception:
        logger.error("Unexpected portfolio benchmark failure")
        return unavailable_comparison(identifier, ProviderError.message), ProviderError()
