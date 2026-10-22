"""One private journal snapshot, with a preflight bound on required price requests."""

from ledger.analytics import entry_labels, journal_snapshot
from ledger.performance import PerformanceRuleError, build_plan, calculate_returns
from ledger.valuation import value_snapshot
from ledger.valuation_services import MAX_VALUATION_INSTRUMENTS, load_valuation
from market_data.errors import ProviderRateLimited

MAX_PERFORMANCE_REQUESTS = 8


def load_performance(user, portfolio_id, start_date, end_date, client_address):
    portfolio, entries = journal_snapshot(user, portfolio_id)
    boundaries = performance_plan(entries, start_date, end_date)
    result, valuations, error = value_performance_plan(boundaries, entries, client_address)
    return portfolio, result, valuations, error


def performance_plan(entries, start_date, end_date):
    """Validate cash-flow timing and request bounds before any price I/O."""
    boundaries = build_plan([entry.as_input() for entry in entries], start_date, end_date)
    if sum(len(point.analysis.positions) for point in boundaries) > MAX_PERFORMANCE_REQUESTS or any(
        len(point.analysis.positions) > MAX_VALUATION_INSTRUMENTS for point in boundaries
    ):
        raise PerformanceRuleError(
            "This period needs more than eight price requests or five holdings on one date. "
            "Choose a period with fewer holdings or cash-flow dates."
        )
    return boundaries


def value_performance_plan(boundaries, entries, client_address):
    """Value a validated plan once; callers can reuse its closing valuation."""
    valuations, error = [], None
    for point in boundaries:
        labels = entry_labels([entry for entry in entries if entry.event_date <= point.as_of])
        if isinstance(error, ProviderRateLimited):
            result = value_snapshot(
                point.analysis,
                point.as_of,
                {},
                {},
                issues={
                    position.security_id: error.message for position in point.analysis.positions
                },
            )
        else:
            result, failure = load_valuation(point.analysis, labels, point.as_of, client_address)
            if failure and (error is None or isinstance(failure, ProviderRateLimited)):
                error = failure
        valuations.append(result)
    return calculate_returns(boundaries, tuple(valuations)), tuple(valuations), error
