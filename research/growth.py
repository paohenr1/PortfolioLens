"""Annual growth from two explicit income periods; no data access or forecasts."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from market_data.contracts import AnnualGrowthStatements
from research.financial_math import exact_change, rounded_percent, valid_financial_number

MIN_ANNUAL_DAYS = 350
MAX_ANNUAL_DAYS = 378
MAX_DURATION_DIFFERENCE = 7
_CLASSIFICATIONS = {"reported", "calculated", "restated"}


@dataclass(frozen=True)
class GrowthMetric:
    label: str
    tag: str
    prior: Decimal | None
    current: Decimal | None
    change: Decimal | None
    percent: Decimal | None
    movement: str | None
    issue: str | None


@dataclass(frozen=True)
class AnnualGrowth:
    metrics: tuple[GrowthMetric, ...]
    prior_days: int | None
    current_days: int | None
    alignment_issue: str | None
    version_warning: str | None


def _days(period):
    if (
        type(period.start_date) is date
        and type(period.end_date) is date
        and period.start_date < period.end_date
    ):
        return period.end_date.toordinal() - period.start_date.toordinal() + 1
    return None


def _alignment_issue(bundle, prior_days, current_days):
    sources = (bundle.prior, bundle.current)
    prior, current = (source.fundamental for source in sources)
    if (
        any(
            period.statement_code != "income_statement" or period.fiscal_period != "FY"
            for period in (prior, current)
        )
        or type(current.fiscal_year) is not int
        or not 1901 <= current.fiscal_year <= 9999
        or type(prior.fiscal_year) is not int
        or prior.fiscal_year != current.fiscal_year - 1
    ):
        return "Two income statements for consecutive annual FY periods are required."
    company = current.company.id
    if (
        not company
        or not bundle.current.security.id
        or prior.company.id != company
        or bundle.prior.security.id != bundle.current.security.id
        or any(source.security.company_id != company for source in sources)
    ):
        return "Both statements must share the same verified instrument and company identity."
    if prior_days is None or current_days is None:
        return "Both income periods require valid supplied date-only start and end dates."
    if prior.end_date.toordinal() + 1 != current.start_date.toordinal():
        return "Prior and current income periods must be adjacent, without a gap or overlap."
    # Fiscal labels alone cannot establish annual comparability. These explicit
    # bounds permit ordinary and week-based years, while withholding stub years.
    if any(not MIN_ANNUAL_DAYS <= days <= MAX_ANNUAL_DAYS for days in (prior_days, current_days)):
        return "Each annual FY must cover 350–378 supplied days; stub periods are unavailable."
    if abs(prior_days - current_days) > MAX_DURATION_DIFFERENCE:
        return "Annual period lengths must differ by at most seven days."
    if any(source.pagination_complete is not True for source in sources):
        return "Both statement responses must be complete."
    if any(len({row.tag for row in source.values}) != len(source.values) for source in sources):
        return "Duplicate source tags make the comparison ambiguous."
    if any(period.type not in _CLASSIFICATIONS for period in (prior, current)):
        return "Both statements require a known reported/calculated/restated classification."
    return None


def _value(source, tag, scope):
    row = next((row for row in source.values if row.tag == tag), None)
    if row is None:
        return None, f"{scope}: source tag {tag} was not supplied."
    if row.value is None:
        return None, f"{scope}: source value {tag} was not supplied."
    if not valid_financial_number(row.value):
        return None, f"{scope}: {tag} is not a supported finite financial number."
    if row.unit != "usd":
        return None, f"{scope}: {tag} requires an explicit provider unit of usd; no conversion."
    return row.value, None


def _movement(prior, current, tag):
    if tag == "netincome":
        if prior < 0:
            if current > 0:
                return "Loss to profit"
            if current == 0:
                return "Loss to break-even"
            return (
                "Loss narrowed"
                if current > prior
                else "Loss widened"
                if current < prior
                else "Loss unchanged"
            )
        if prior == 0:
            return (
                "Break-even to profit"
                if current > 0
                else "Break-even to loss"
                if current < 0
                else "Unchanged"
            )
        if current < 0:
            return "Profit to loss"
        if current == 0:
            return "Profit to break-even"
    return "Increased" if current > prior else "Decreased" if current < prior else "Unchanged"


def calculate_annual_growth(bundle: AnnualGrowthStatements) -> AnnualGrowth:
    prior_days, current_days = _days(bundle.prior.fundamental), _days(bundle.current.fundamental)
    alignment = _alignment_issue(bundle, prior_days, current_days)
    warning = None
    if not alignment and bundle.prior.fundamental.type != bundle.current.fundamental.type:
        warning = (
            "Statement classifications differ. These are currently retrieved versions; "
            "matching dates do not establish a shared historical revision."
        )
    metrics = []
    for label, tag in (("Revenue growth", "totalrevenue"), ("Net income growth", "netincome")):
        prior = current = change = percent = movement = None
        issue = alignment
        if not alignment:
            prior, prior_issue = _value(bundle.prior, tag, "Prior statement")
            current, current_issue = _value(bundle.current, tag, "Current statement")
            issue = prior_issue or current_issue
            if issue is None:
                change = exact_change(prior, current)
                movement = _movement(prior, current, tag)
                if prior > 0:
                    percent = rounded_percent(change, prior)
                else:
                    issue = (
                        "Percentage growth requires a positive prior value; "
                        "the dollar change remains available."
                    )
        metrics.append(GrowthMetric(label, tag, prior, current, change, percent, movement, issue))
    return AnnualGrowth(tuple(metrics), prior_days, current_days, alignment, warning)
