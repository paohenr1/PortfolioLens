"""Selected-FY P/E with exact-date raw closes; pure calculations, no I/O.

A company association does not establish share-class or split compatibility.
The caller must supply an explicit user confirmation before showing multiples.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from market_data.contracts import AnnualValuationInputs
from research.financial_math import rounded_multiple, valid_financial_number
from research.growth import MAX_ANNUAL_DAYS, MIN_ANNUAL_DAYS


@dataclass(frozen=True)
class EarningsMultiple:
    label: str
    tag: str
    eps: Decimal | None
    multiple: Decimal | None
    issue: str | None


@dataclass(frozen=True)
class AnnualMultiples:
    raw_close: Decimal | None
    price_date: date
    annual_days: int | None
    metrics: tuple[EarningsMultiple, ...]
    alignment_issue: str | None


def _income_issue(source, price_date):
    period = source.fundamental
    if (
        period.statement_code != "income_statement"
        or period.fiscal_period != "FY"
        or type(period.fiscal_year) is not int
        or not 1900 <= period.fiscal_year <= 9999
    ):
        return "An explicit annual FY income statement is required."
    if (
        not source.security.id
        or not period.company.id
        or (source.security.company_id != period.company.id)
    ):
        return "The statement requires a verified instrument and company identity."
    if (
        type(period.start_date) is not date
        or type(period.end_date) is not date
        or period.start_date >= period.end_date
    ):
        return "Annual income requires valid supplied date-only start and end dates."
    days = (period.end_date - period.start_date).days + 1
    if not MIN_ANNUAL_DAYS <= days <= MAX_ANNUAL_DAYS:
        return "Annual FY income must cover 350–378 days; stub periods are unavailable."
    if type(price_date) is not date or price_date < period.end_date:
        return "The selected price date must be on or after the supplied income period end."
    if source.pagination_complete is not True:
        return "The income statement response must be complete."
    if len({row.tag for row in source.values}) != len(source.values):
        return "Duplicate source tags make the earnings inputs ambiguous."
    if period.type not in {"reported", "calculated", "restated"}:
        return "The statement requires a known reported/calculated/restated classification."
    return None


def _raw_close(bundle, price_date):
    history, security = bundle.prices, bundle.income.security
    if (
        type(price_date) is not date
        or history.start_date != price_date
        or history.end_date != price_date
        or history.security.id != security.id
        or history.security.currency != "USD"
        or security.currency != "USD"
        or not security.exchange_mic
        or history.security.exchange_mic != security.exchange_mic
        or history.security.company_id not in (None, security.company_id)
        or history.pagination_complete is not True
        or len(history.observations) != 1
        or not isinstance(history.retrieved_at, datetime)
        or history.retrieved_at.tzinfo is None
        or history.retrieved_at.utcoffset() is None
        or price_date > history.retrieved_at.astimezone(UTC).date()
    ):
        return None
    observation = history.observations[0]
    close = observation.close
    if (
        type(observation.date) is not date
        or observation.date != price_date
        or observation.intraperiod is not False
        or not valid_financial_number(close)
        or not Decimal("0") <= close <= Decimal("1e12")
        or len(close.as_tuple().digits) > 28
        or not -18 <= close.as_tuple().exponent <= 12
    ):
        return None
    # Adjusted closes can embed dividends/splits on a different share basis.
    # An unavailable raw close is never replaced by adjusted/prior-day prices.
    return close


def calculate_annual_multiples(
    bundle: AnnualValuationInputs, price_date: date, *, basis_confirmed: bool
) -> AnnualMultiples:
    """Raw USD close / positive FY USD-per-share EPS, independently by tag.

    These are currently retrieved statement versions, not TTM/forward or
    historical-as-known multiples. Confirmation is an assumption, not verification.
    """
    source, period = bundle.income, bundle.income.fundamental
    days = (
        (period.end_date - period.start_date).days + 1
        if type(period.start_date) is date and type(period.end_date) is date
        else None
    )
    alignment = _income_issue(source, price_date)
    close = _raw_close(bundle, price_date)
    common_issue = alignment
    if common_issue is None and basis_confirmed is not True:
        common_issue = "Confirm the selected instrument's share class and EPS/price split basis."
    if common_issue is None and close is None:
        common_issue = (
            "No complete, confirmed raw USD close matching this exact date, instrument and venue."
        )
    metrics = []
    for label, tag in (("Basic FY P/E", "basiceps"), ("Diluted FY P/E", "dilutedeps")):
        eps = multiple = None
        issue = common_issue
        if issue is None:
            row = next((row for row in source.values if row.tag == tag), None)
            if row is None:
                issue = f"Source tag {tag} was not supplied."
            elif row.value is None:
                issue = f"Source value {tag} was not supplied."
            elif not valid_financial_number(row.value):
                issue = f"{tag} is not a supported finite financial number."
            elif row.unit != "usdpershare":
                issue = f"{tag} requires an explicit provider unit of usdpershare; no conversion."
            else:
                eps = row.value
                if eps <= 0:
                    issue = "P/E requires positive EPS; zero or negative earnings are unavailable."
                else:
                    multiple = rounded_multiple(close, eps)
        metrics.append(EarningsMultiple(label, tag, eps, multiple, issue))
    return AnnualMultiples(close, price_date, days, tuple(metrics), alignment)
