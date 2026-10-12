"""Bounded session plans and exact daily linking; no market-data or database I/O."""

from datetime import date, timedelta
from fractions import Fraction

import exchange_calendars

from ledger.domain import ZERO
from ledger.fifo import analyze
from ledger.forms import ledger_today
from ledger.performance import (
    Boundary,
    DailySeries,
    PerformanceRuleError,
    _percent,
    build_plan,
    calculate_returns,
)

MAX_SERIES_DAYS = 90
MIN_SERIES_DATE = date(2000, 1, 1)


def session_dates(start_date, end_date):
    if (
        type(start_date) is not date
        or type(end_date) is not date
        or not MIN_SERIES_DATE <= start_date < end_date < ledger_today()
        or (end_date - start_date).days + 1 > MAX_SERIES_DAYS
    ):
        raise PerformanceRuleError(
            "Choose increasing completed dates from 2000, covering at most 90 calendar days."
        )
    # The maintained calendar includes holidays, early closes and extraordinary
    # closures. All supported U.S. equity venues use this regular-session grid.
    # Padding also lets an all-weekend request fail with a useful validation error.
    calendar = exchange_calendars.get_calendar(
        "XNYS", start=start_date - timedelta(days=7), end=end_date + timedelta(days=7)
    )
    days = tuple(point.date() for point in calendar.sessions_in_range(start_date, end_date))
    if len(days) < 2 or days[0] != start_date or days[-1] != end_date:
        raise PerformanceRuleError("Opening and closing dates must both be U.S. equity sessions.")
    return days


def build_daily_plan(events, start_date, end_date):
    days = session_dates(start_date, end_date)
    events = sorted(events, key=lambda event: (event.event_date, event.sequence))
    # Reuse full journal validation and the existing EOD timing contract. Its
    # 16 cash-flow boundary limit remains explicit for this first series module.
    flow_points = build_plan(events, start_date, end_date)
    sessions = set(days)
    if any(
        start_date < event.event_date <= end_date and event.event_date not in sessions
        for event in events
    ):
        raise PerformanceRuleError(
            "Activity after the opening date must be recorded on a U.S. equity session. "
            "Non-session activity cannot be assigned a close automatically."
        )
    flows = {point.as_of: point.external_flow for point in flow_points}
    return tuple(
        Boundary(
            day,
            analyze([event for event in events if event.event_date <= day]),
            flows.get(day, ZERO),
        )
        for day in days
    )


def calculate_daily_returns(boundaries, valuations):
    if len(boundaries) != len(valuations) or not 2 <= len(boundaries) <= MAX_SERIES_DAYS:
        raise PerformanceRuleError("A matching valuation is required at every session.")
    if tuple(point.as_of for point in boundaries) != session_dates(
        boundaries[0].as_of, boundaries[-1].as_of
    ):
        raise PerformanceRuleError("The daily plan must contain every consecutive session.")
    periods, linked, issue = [], Fraction(1), None
    for index in range(1, len(boundaries)):
        result = calculate_returns(
            boundaries[index - 1 : index + 1], valuations[index - 1 : index + 1]
        )
        period = result.periods[0]
        periods.append(period)
        issue = issue or result.issue
        if result.issue is None:
            # These cent values have already passed reconciliation. Use the exact
            # factor, rather than the four-decimal displayed daily percentage.
            linked *= Fraction(period.before_flow_value) / Fraction(period.start_value)
    return DailySeries(
        start_date=boundaries[0].as_of,
        end_date=boundaries[-1].as_of,
        periods=tuple(periods),
        return_percent=_percent(linked) if issue is None else None,
        issue=issue,
    )
