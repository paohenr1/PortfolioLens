"""One owner-scoped journal snapshot for the inline overview and bounded prices."""

from ledger.allocations import allocation_weights
from ledger.analytics import entry_labels, journal_snapshot
from ledger.fifo import analyze
from ledger.performance import PerformanceRuleError
from ledger.performance_services import performance_plan, value_performance_plan
from ledger.valuation_services import ValuationLimitError, load_valuation


def overview_context(user, portfolio_id, *, dates=None, client_address="unknown"):
    portfolio, entries = journal_snapshot(user, portfolio_id)
    analysis = analyze([entry.as_input() for entry in entries])
    labels = entry_labels(entries)
    context = {
        "portfolio": portfolio,
        "analysis": analysis,
        "position_count": len(analysis.positions),
        "recent_entries": list(reversed(entries[-5:])),
        "position_preview": [
            {"position": item, "instrument": labels[item.security_id]}
            for item in analysis.positions[:5]
        ],
    }
    if dates is None:
        return context, None
    start, end = dates
    try:
        plan = performance_plan(entries, start, end)
    except PerformanceRuleError as error:
        # Timing or request limits can block returns while closing value is useful.
        context["performance_issue"] = str(error)
        closing_entries = [entry for entry in entries if entry.event_date <= end]
        closing_analysis = analyze([entry.as_input() for entry in closing_entries])
        try:
            valuation, provider_error = load_valuation(
                closing_analysis, entry_labels(closing_entries), end, client_address
            )
        except ValuationLimitError as limit:
            context["valuation_issue"] = str(limit)
            return context, None
    else:
        performance, valuations, provider_error = value_performance_plan(
            plan, entries, client_address
        )
        context["performance"] = performance
        valuation = valuations[-1]
    closing_labels = entry_labels([entry for entry in entries if entry.event_date <= end])
    allocation = allocation_weights(valuation)
    weights = {row.security_id: row.weight for row in allocation.rows}
    context.update(
        valuation=valuation,
        allocation_issue=allocation.issue,
        cash_weight=weights[None],
        valued_rows=[
            {
                "value": row,
                "instrument": closing_labels[row.position.security_id],
                "weight": weights[row.position.security_id],
            }
            for row in valuation.rows
        ],
    )
    return context, provider_error
