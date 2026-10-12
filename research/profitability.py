"""Selected-period margins from one standardized statement; no I/O or forecasts."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from market_data.contracts import FinancialStatement
from research.financial_math import rounded_percent, valid_financial_number

# Intrinio's standardized statement uses the total-prefixed profit tags.
# Similar shorter names are not substitutes for these supplied observations.
_MARGINS = (
    ("Gross profit margin", "totalgrossprofit", "Gross profit ÷ revenue × 100."),
    ("Operating profit margin", "totaloperatingincome", "Operating income ÷ revenue × 100."),
    ("Net profit margin", "netincome", "Net income ÷ revenue × 100."),
)


@dataclass(frozen=True)
class ProfitMargin:
    label: str
    numerator_tag: str
    definition: str
    percent: Decimal | None
    issue: str | None


def profit_margins(statement: FinancialStatement) -> tuple[ProfitMargin, ...]:
    """Require explicit period dates, complete data, USD units, and positive revenue."""
    period = statement.fundamental
    if period.statement_code != "income_statement":
        return ()
    issue = None
    if (
        period.fiscal_period not in {"FY", "Q1", "Q2", "Q3", "Q4"}
        or type(period.start_date) is not date
        or type(period.end_date) is not date
        or period.start_date >= period.end_date
    ):
        issue = "A supported fiscal period with valid start and end dates is required."
    elif statement.pagination_complete is not True:
        issue = "Margins are unavailable for a partial statement response."
    elif len({row.tag for row in statement.values}) != len(statement.values):
        issue = "Duplicate source tags make this statement ambiguous."

    lookup = {row.tag: row for row in statement.values}

    def source_issue(tag):
        row = lookup.get(tag)
        if row is None:
            return f"Source tag {tag} was not supplied in this response."
        if row.value is None:
            return f"Source value {tag} was not supplied."
        if not valid_financial_number(row.value):
            return f"Source value {tag} is not a supported finite financial number."
        if row.unit != "usd":
            return f"Source tag {tag} requires an explicit provider unit of usd; no conversion."
        return None

    revenue_issue = issue or source_issue("totalrevenue")
    if revenue_issue is None and lookup["totalrevenue"].value <= 0:
        revenue_issue = "Revenue must be positive; zero or negative revenue has no margin here."
    margins = []
    for label, tag, definition in _MARGINS:
        metric_issue = revenue_issue or source_issue(tag)
        margins.append(
            ProfitMargin(
                label,
                tag,
                definition,
                None
                if metric_issue
                else rounded_percent(lookup[tag].value, lookup["totalrevenue"].value),
                metric_issue,
            )
        )
    return tuple(margins)
