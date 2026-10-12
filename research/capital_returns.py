"""Annual return on average assets/equity; inputs and period alignment are explicit."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from market_data.contracts import AnnualProfitabilityStatements
from research.financial_math import average_balance, rounded_percent, valid_financial_number


@dataclass(frozen=True)
class ReturnOnBalance:
    label: str
    balance_tag: str
    opening: Decimal | None
    closing: Decimal | None
    average: Decimal | None
    percent: Decimal | None
    issue: str | None


@dataclass(frozen=True)
class CapitalReturns:
    net_income: Decimal | None
    metrics: tuple[ReturnOnBalance, ...]
    alignment_issue: str | None


def _alignment_issue(bundle):
    income, opening, closing = bundle.income, bundle.opening_balance, bundle.closing_balance
    periods = [source.fundamental for source in (income, opening, closing)]
    if (
        periods[0].statement_code != "income_statement"
        or any(period.statement_code != "balance_sheet_statement" for period in periods[1:])
        or any(period.fiscal_period != "FY" for period in periods)
        or type(periods[0].fiscal_year) is not int
        or not 1901 <= periods[0].fiscal_year <= 9999
        or any(type(period.fiscal_year) is not int for period in periods[1:])
        or periods[1].fiscal_year != periods[0].fiscal_year - 1
        or periods[2].fiscal_year != periods[0].fiscal_year
    ):
        return "An annual income statement and preceding/current FY balance sheets are required."
    company_id = periods[0].company.id
    if (
        not company_id
        or not income.security.id
        or any(period.company.id != company_id for period in periods)
        or any(source.security.id != income.security.id for source in (opening, closing))
        or any(source.security.company_id != company_id for source in (income, opening, closing))
    ):
        return "All statements must have the same verified instrument and company identity."
    start, end = periods[0].start_date, periods[0].end_date
    if type(start) is not date or type(end) is not date or start >= end:
        return "The income period requires valid supplied start and end dates."
    if (
        type(periods[1].end_date) is not date
        or type(periods[2].end_date) is not date
        or periods[1].end_date.toordinal() != start.toordinal() - 1
        or periods[2].end_date != end
    ):
        return "Balance-sheet dates must be the day before income starts and the income end date."
    if any(source.pagination_complete is not True for source in (income, opening, closing)):
        return "All three statement responses must be complete."
    if any(
        len({row.tag for row in source.values}) != len(source.values)
        for source in (income, opening, closing)
    ):
        return "Duplicate source tags make the statement inputs ambiguous."
    return None


def _source(source, tag, scope):
    row = next((row for row in source.values if row.tag == tag), None)
    if row is None:
        return None, f"{scope}: source tag {tag} was not supplied."
    if row.value is None:
        return None, f"{scope}: source value {tag} was not supplied."
    if not valid_financial_number(row.value):
        return None, f"{scope}: source value {tag} is not a supported finite financial number."
    if row.unit != "usd":
        return None, f"{scope}: {tag} requires an explicit provider unit of usd; no conversion."
    return row.value, None


def calculate_capital_returns(bundle: AnnualProfitabilityStatements) -> CapitalReturns:
    """Net income / mean of two positive endpoint balances, with no annualization."""
    alignment = _alignment_issue(bundle)
    net_income, numerator_issue = (
        (None, alignment) if alignment else _source(bundle.income, "netincome", "Income statement")
    )
    metrics = []
    for label, tag in (
        ("Return on average assets", "totalassets"),
        ("Return on average equity", "totalequity"),
    ):
        opening = closing = average = percent = None
        issue = numerator_issue
        if not issue:
            opening, issue = _source(bundle.opening_balance, tag, "Opening balance sheet")
        if not issue:
            closing, issue = _source(bundle.closing_balance, tag, "Closing balance sheet")
        if not issue:
            if opening <= 0 or closing <= 0:
                issue = (
                    "Both endpoint balances must be positive; "
                    "zero/negative balances are unavailable."
                )
            else:
                average = average_balance(opening, closing)
                percent = rounded_percent(net_income, average)
        metrics.append(ReturnOnBalance(label, tag, opening, closing, average, percent, issue))
    return CapitalReturns(net_income, tuple(metrics), alignment)
