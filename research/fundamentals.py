"""Presentation of standardized observations and explicit selected-period margins."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from market_data.contracts import FinancialStatement
from market_data.fundamentals import STATEMENTS
from research.profitability import profit_margins

_UNITS = {"usd": "USD", "usdpershare": "USD per share", "shares": "Shares"}
_METRICS = {
    "income_statement": [
        ("totalrevenue", "Revenue", "Provider-standardized total revenue for the selected period."),
        ("netincome", "Net income", "Provider-standardized net income for the selected period."),
        (
            "basiceps",
            "Basic EPS",
            "Provider-standardized earnings per basic share for the selected period.",
        ),
        (
            "dilutedeps",
            "Diluted EPS",
            "Provider-standardized earnings per diluted share for the selected period.",
        ),
    ],
    "balance_sheet_statement": [
        ("totalassets", "Total assets", "Provider-standardized assets at the selected period end."),
        (
            "totalliabilities",
            "Total liabilities",
            "Provider-standardized liabilities at the selected period end.",
        ),
        ("totalequity", "Total equity", "Provider-standardized equity at the selected period end."),
    ],
    "cash_flow_statement": [
        (
            "netcashfromoperatingactivities",
            "Operating cash flow",
            "Provider-standardized net cash from operating activities for the selected period.",
        ),
        (
            "netcashfrominvestingactivities",
            "Investing cash flow",
            "Provider-standardized net cash from investing activities for the selected period.",
        ),
        (
            "netcashfromfinancingactivities",
            "Financing cash flow",
            "Provider-standardized net cash from financing activities for the selected period.",
        ),
    ],
}


def financial_text(value: Decimal | None):
    if value is None:
        return "Unavailable"
    text = format(value, ",f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def unit_text(unit: str | None):
    if unit is None:
        return "Unavailable — no unit inferred"
    return _UNITS.get(unit, unit + " (provider unit; no conversion)")


def metadata_time(value: date | datetime | None):
    if value is None:
        return "Unavailable"
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.isoformat(sep=" ") + " (timezone unavailable)"
        return value.astimezone(UTC).isoformat(sep=" ")
    return value.isoformat() + " (date only)"


@dataclass(frozen=True)
class StatementRow:
    tag: str
    label: str
    value: str
    unit: str


@dataclass(frozen=True)
class Metric:
    label: str
    tag: str
    value: str
    unit: str
    definition: str
    availability: str


def statement_presentation(statement: FinancialStatement):
    lookup = {value.tag: value for value in statement.values}
    metrics = []
    for tag, label, definition in _METRICS[statement.fundamental.statement_code]:
        value = lookup.get(tag)
        metrics.append(
            Metric(
                label,
                tag,
                financial_text(value.value if value else None),
                unit_text(value.unit if value else None),
                definition,
                "Tag not supplied in this response"
                if value is None
                else "Value not supplied"
                if value.value is None
                else "Supplied observation",
            )
        )
    return {
        "profit_margins": profit_margins(statement),
        "statement_label": STATEMENTS[statement.fundamental.statement_code],
        "metrics": tuple(metrics),
        "rows": tuple(
            StatementRow(
                row.tag, row.name or row.tag, financial_text(row.value), unit_text(row.unit)
            )
            for row in statement.values
        ),
        "filing_time": metadata_time(statement.fundamental.filing_date),
        "updated_time": metadata_time(statement.fundamental.updated_date),
        "calculable_time": metadata_time(statement.fundamental.first_calculable),
    }
