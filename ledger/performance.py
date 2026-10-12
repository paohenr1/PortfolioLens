"""Pure time-weighted returns for explicitly confirmed end-of-day external flows."""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext
from fractions import Fraction

from ledger.domain import ZERO
from ledger.fifo import Analysis, analyze
from ledger.valuation import Valuation

EXTERNAL_KINDS = {"DEPOSIT", "WITHDRAWAL"}
MAX_BOUNDARIES = 16
RETURN_PRECISION = Decimal("0.0001")


class PerformanceRuleError(ValueError):
    pass


@dataclass(frozen=True)
class Boundary:
    as_of: date
    analysis: Analysis
    external_flow: Decimal


@dataclass(frozen=True)
class Subperiod:
    start_date: date
    end_date: date
    start_value: Decimal | None
    end_value: Decimal | None
    external_flow: Decimal
    before_flow_value: Decimal | None
    return_percent: Decimal | None
    issue: str | None


@dataclass(frozen=True)
class Performance:
    start_date: date
    end_date: date
    periods: tuple[Subperiod, ...]
    return_percent: Decimal | None
    issue: str | None


@dataclass(frozen=True)
class DailySeries(Performance):
    """Every consecutive session, validated by the daily planner before linking.

    This distinct contract prevents cash-flow boundary subperiods from being
    mistaken for daily observations when calculating risk statistics.
    """


def build_plan(events, start_date, end_date):
    if (
        type(start_date) is not date
        or type(end_date) is not date
        or not date(1900, 1, 1) <= start_date < end_date
        or (end_date - start_date).days + 1 > 366
    ):
        raise PerformanceRuleError("Choose increasing dates covering at most 366 calendar days.")
    events = sorted(events, key=lambda event: (event.event_date, event.sequence))
    analyze(events)  # Validate the full journal, including later historical prefixes.
    flows, activity = {}, {}
    with localcontext() as context:
        context.prec = 64
        for event in events:
            if not start_date < event.event_date <= end_date:
                continue
            day = activity.setdefault(event.event_date, [])
            day.append(event)
            if event.kind in EXTERNAL_KINDS:
                flows[event.event_date] = flows.get(event.event_date, ZERO) + event.cash_delta
        for day in activity.values():
            flow_seen = False
            for event in day:
                if event.kind in EXTERNAL_KINDS:
                    flow_seen = True
                elif flow_seen:
                    # A same-day deposit funding a trade is intraday, not an EOD
                    # flow. Daily prices cannot reconstruct the value at that flow.
                    raise PerformanceRuleError(
                        "Within this period, deposits and withdrawals must follow all other "
                        "same-day activity and be confirmed as end-of-day flows."
                    )
        dates = sorted({start_date, end_date, *flows})
        if len(dates) > MAX_BOUNDARIES:
            raise PerformanceRuleError("Choose a period requiring at most 16 valuation dates.")
        return tuple(
            Boundary(
                day,
                analyze([event for event in events if event.event_date <= day]),
                flows.get(day, ZERO),
            )
            for day in dates
        )


def _money(value, *, signed=False):
    if (
        not isinstance(value, Decimal)
        or not value.is_finite()
        or (not signed and value < 0)
        or value.copy_abs() > Decimal("1e26")
        or value.as_tuple().exponent < -18
        or len(value.as_tuple().digits) > 40
    ):
        return None
    number = Fraction(value)
    return number if (number * 100).denominator == 1 else None


def _percent(factor):
    # Chain exact rational factors; rounding each subperiod before linking would
    # change cumulative performance. Convert only final/display values to Decimal.
    with localcontext() as context:
        difference = factor - 1
        # A long chain can have more than 64 significant integer digits. Input
        # values and 16 boundaries bound this precision; don't round the chain.
        context.prec = max(
            64, len(str(difference.numerator)) + len(str(difference.denominator)) + 8
        )
        result = Decimal(difference.numerator) / Decimal(difference.denominator) * 100
        return result.quantize(RETURN_PRECISION, rounding=ROUND_HALF_UP)


def _total(valuation, boundary):
    total, cash, market = (
        _money(value)
        for value in (
            valuation.total_value,
            valuation.cash,
            valuation.market_value,
        )
    )
    amounts = [_money(row.market_value) for row in valuation.rows]
    identifiers = [row.position.security_id for row in valuation.rows]
    if (
        total is None
        or cash is None
        or market is None
        or None in amounts
        or sum(amounts) != market
        or cash + market != total
        or len(identifiers) != len(set(identifiers))
        or valuation.cash != boundary.analysis.cash
        or tuple(row.position for row in valuation.rows) != boundary.analysis.positions
    ):
        return None
    return total


def calculate_returns(boundaries, valuations: tuple[Valuation, ...]):
    if len(boundaries) != len(valuations) or not 2 <= len(boundaries) <= MAX_BOUNDARIES:
        raise PerformanceRuleError("A matching valuation is required at every boundary.")
    if any(
        left.as_of >= right.as_of
        for left, right in zip(boundaries[:-1], boundaries[1:], strict=True)
    ):
        raise PerformanceRuleError("Valuation dates must increase.")
    periods, factors, overall_issue = [], [], None
    for index in range(1, len(boundaries)):
        previous, boundary = boundaries[index - 1], boundaries[index]
        opening, closing = valuations[index - 1], valuations[index]
        start, end = _total(opening, previous), _total(closing, boundary)
        flow = _money(boundary.external_flow, signed=True)
        issue, before, percent = None, None, None
        if opening.as_of != previous.as_of or closing.as_of != boundary.as_of:
            issue = "Valuation dates do not match the requested boundaries."
        elif start is None or end is None or flow is None:
            issue = "A complete valid valuation is required at every boundary."
        elif start <= 0:
            issue = "Each subperiod requires a positive opening value."
        elif end - flow < 0:
            issue = "The value before the end-of-day flow cannot be negative."
        else:
            adjusted = end - flow
            with localcontext() as context:
                context.prec = 64
                before = (Decimal(adjusted.numerator) / Decimal(adjusted.denominator)).quantize(
                    Decimal("0.01")
                )
            factor = adjusted / start
            factors.append(factor)
            percent = _percent(factor)
        overall_issue = overall_issue or issue
        periods.append(
            Subperiod(
                previous.as_of,
                boundary.as_of,
                opening.total_value,
                closing.total_value,
                boundary.external_flow,
                before,
                percent,
                issue,
            )
        )
    cumulative = None
    if overall_issue is None:
        linked = Fraction(1)
        for factor in factors:
            linked *= factor
        cumulative = _percent(linked)
    return Performance(
        boundaries[0].as_of, boundaries[-1].as_of, tuple(periods), cumulative, overall_issue
    )
