"""Annual USD statement observations and adjacent changes; no I/O or inference."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from fractions import Fraction

from market_data.contracts import AnnualStatementSeries
from research.financial_math import exact_change, rounded_percent, valid_financial_number
from research.fundamentals import financial_text
from research.growth import MAX_ANNUAL_DAYS, MAX_DURATION_DIFFERENCE, MIN_ANNUAL_DAYS

TREND_METRICS = {
    "income_statement": (
        ("Revenue", "totalrevenue"),
        # Match the actual standardized statement tag, also used by margins.
        ("Operating income", "totaloperatingincome"),
        ("Net income", "netincome"),
    ),
    "balance_sheet_statement": (
        ("Total assets", "totalassets"),
        ("Total liabilities", "totalliabilities"),
        ("Total equity", "totalequity"),
    ),
    "cash_flow_statement": (
        ("Operating cash flow", "netcashfromoperatingactivities"),
        ("Investing cash flow", "netcashfrominvestingactivities"),
        ("Financing cash flow", "netcashfromfinancingactivities"),
    ),
}


@dataclass(frozen=True)
class TrendValue:
    year: int
    value: Decimal | None
    issue: str | None


@dataclass(frozen=True)
class TrendChange:
    prior_year: int
    current_year: int
    change: Decimal | None
    percent: Decimal | None
    issue: str | None
    warning: str | None


@dataclass(frozen=True)
class TrendMetric:
    label: str
    tag: str
    values: tuple[TrendValue, ...]
    changes: tuple[TrendChange, ...]


@dataclass(frozen=True)
class StatementTrends:
    metrics: tuple[TrendMetric, ...]
    alignment_issue: str | None


def _series_issue(sources):
    if not 2 <= len(sources) <= 4:
        return "Two to four explicitly selected annual statements are required."
    first = sources[0]
    code, company, security = (
        first.fundamental.statement_code,
        first.fundamental.company.id,
        first.security.id,
    )
    if code not in TREND_METRICS:
        return "Choose a supported income, balance-sheet or cash-flow statement."
    if (
        not company
        or not security
        or any(
            source.fundamental.company.id != company
            or source.security.company_id != company
            or source.security.id != security
            or source.fundamental.statement_code != code
            for source in sources
        )
    ):
        return "All selected statements must share one verified instrument, company and type."
    years = [source.fundamental.fiscal_year for source in sources]
    if (
        any(type(year) is not int or not 1900 <= year <= 9999 for year in years)
        or years != list(range(years[0], years[0] + len(years)))
        or any(source.fundamental.fiscal_period != "FY" for source in sources)
    ):
        return "Statements must be consecutive FY years ordered oldest to newest."
    return None


def _days(source):
    period = source.fundamental
    if type(period.start_date) is date and type(period.end_date) is date:
        return (period.end_date - period.start_date).days + 1
    return None


def _source_issue(source):
    period = source.fundamental
    if type(period.end_date) is not date:
        return "The supplied period end must be a valid date-only observation."
    if period.statement_code != "balance_sheet_statement":
        days = _days(source)
        if days is None or not MIN_ANNUAL_DAYS <= days <= MAX_ANNUAL_DAYS:
            return (
                "Annual flow periods require 350–378 supplied days; "
                "stub/missing dates are unavailable."
            )
    if source.pagination_complete is not True:
        return "The statement response is partial; observations are withheld."
    if len({row.tag for row in source.values}) != len(source.values):
        return "Duplicate source tags make this statement ambiguous."
    if period.type not in {"reported", "calculated", "restated"}:
        return "The statement classification must be known reported/calculated/restated."
    return None


def _value(source, tag, issue):
    if issue:
        return None, issue
    row = next((row for row in source.values if row.tag == tag), None)
    if row is None:
        return None, f"Source tag {tag} was not supplied."
    if row.value is None:
        return None, f"Source value {tag} was not supplied."
    if not valid_financial_number(row.value):
        return None, f"{tag} is not a supported finite financial number."
    if row.unit != "usd":
        return None, f"{tag} requires an explicit provider unit of usd; no conversion."
    return row.value, None


def _pair_issue(prior, current):
    if current.fundamental.statement_code == "balance_sheet_statement":
        distance = (current.fundamental.end_date - prior.fundamental.end_date).days
        if not MIN_ANNUAL_DAYS <= distance <= MAX_ANNUAL_DAYS:
            return "Balance-sheet dates must advance by 350–378 days for an annual change."
    else:
        if prior.fundamental.end_date.toordinal() + 1 != current.fundamental.start_date.toordinal():
            return "Annual flow periods must be adjacent, without a gap or overlap."
        if abs(_days(prior) - _days(current)) > MAX_DURATION_DIFFERENCE:
            return "Annual flow lengths must differ by at most seven days."
    return None


def calculate_statement_trends(bundle: AnnualStatementSeries) -> StatementTrends:
    """Keep supplied observations; compare only valid adjacent pairs.

    An unavailable year breaks each affected comparison. Never interpolate,
    skip to the previous available year, sum balance sheets or infer currency.
    """
    sources = bundle.statements
    alignment = _series_issue(sources)
    if alignment:
        return StatementTrends((), alignment)
    source_issues = tuple(_source_issue(source) for source in sources)
    metrics = []
    for label, tag in TREND_METRICS[sources[0].fundamental.statement_code]:
        values = tuple(
            TrendValue(source.fundamental.fiscal_year, *_value(source, tag, issue))
            for source, issue in zip(sources, source_issues, strict=True)
        )
        changes = []
        for index in range(1, len(sources)):
            prior, current = sources[index - 1], sources[index]
            prior_value, current_value = values[index - 1], values[index]
            delta = percent = warning = None
            issue = prior_value.issue or current_value.issue
            if issue is None:
                issue = _pair_issue(prior, current)
            if issue is None:
                if prior.fundamental.type != current.fundamental.type:
                    warning = "Classifications differ; these are currently retrieved versions."
                if current.fundamental.statement_code != "balance_sheet_statement" and (
                    _days(prior) != _days(current)
                ):
                    warning = (
                        warning + " " if warning else ""
                    ) + "Period lengths differ; no per-day adjustment."
                delta = exact_change(prior_value.value, current_value.value)
                if prior_value.value > 0:
                    percent = rounded_percent(delta, prior_value.value)
                else:
                    issue = (
                        "Percentage change requires a positive prior value; "
                        "dollar change remains available."
                    )
            changes.append(
                TrendChange(prior_value.year, current_value.year, delta, percent, issue, warning)
            )
        metrics.append(TrendMetric(label, tag, values, tuple(changes)))
    return StatementTrends(tuple(metrics), None)


def trend_chart(metric: TrendMetric):
    """Exact bounded bar geometry; missing years have no bar or selectable point."""
    maximum = max(
        (row.value.copy_abs() for row in metric.values if row.value is not None), default=Decimal(0)
    )
    bars = []
    selectable_seen = False
    for index, row in enumerate(metric.values):
        x = 60 + index * 520 // (len(metric.values) - 1)
        height = (
            int(abs(Fraction(row.value)) / Fraction(maximum) * 120)
            if maximum and row.value is not None
            else 0
        )
        positive = row.value is not None and row.value >= 0
        bars.append(
            {
                "year": row.year,
                "x": x,
                "bar_x": x - 25,
                "y": 150 - height if positive else 150,
                "height": height,
                "cy": 150 - height if positive else 150 + height,
                "available": row.value is not None,
                "tabindex": 0 if row.value is not None and not selectable_seen else -1,
                "label": f"{row.year} FY · {metric.label} · {financial_text(row.value)} USD",
            }
        )
        selectable_seen = selectable_seen or row.value is not None
    return {
        "bars": tuple(bars),
        "scale": financial_text(maximum),
        "available": any(row.value is not None for row in metric.values),
    }
