"""Strict statement metadata and values; no forecasts or inferred currencies."""

import re
from datetime import UTC, date, datetime
from decimal import Decimal

from market_data.contracts import Company, FinancialValue, Fundamental
from market_data.errors import InvalidResponse
from market_data.fields import optional_text, valid_provider_id

STATEMENTS = {
    "income_statement": "Income statement",
    "balance_sheet_statement": "Balance sheet",
    "cash_flow_statement": "Cash flow statement",
}
PERIODS = {
    "FY": "Annual (FY)",
    "Q1": "Quarter 1",
    "Q2": "Quarter 2",
    "Q3": "Quarter 3",
    "Q4": "Quarter 4",
}
MAX_FINANCIAL_ROWS = 200
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?")


def validate_statement_request(statement_code, fiscal_year, fiscal_period):
    if statement_code not in STATEMENTS or fiscal_period not in PERIODS:
        raise ValueError("Choose an income, balance-sheet, or cash-flow statement and FY/Q1–Q4.")
    # Fiscal-year naming can lead the calendar year; observation dates stay bounded.
    if type(fiscal_year) is not int or not 1900 <= fiscal_year <= datetime.now(UTC).year + 1:
        raise ValueError("Choose a supported fiscal year, from 1900 through next calendar year.")


def validate_annual_series_request(statement_code, end_year, years):
    """Bound the complete range before transport; never silently shorten it."""
    if type(years) is not int or not 2 <= years <= 4:
        raise ValueError("Choose two to four annual periods.")
    validate_statement_request(statement_code, end_year, "FY")
    validate_statement_request(statement_code, end_year - years + 1, "FY")


def _date_field(payload, key):
    text = optional_text(payload, key, limit=10)
    if text is None:
        return None
    if _DATE.fullmatch(text) is None:
        raise InvalidResponse()
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise InvalidResponse() from None


def _timestamp_field(payload, key):
    text = optional_text(payload, key, limit=40)
    if text is None:
        return None
    if _DATE.fullmatch(text):
        return _date_field(payload, key)
    if _TIMESTAMP.fullmatch(text) is None:
        raise InvalidResponse()
    try:
        # Preserve a missing timezone rather than interpreting it as UTC.
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise InvalidResponse() from None


def normalize_company(payload):
    if not isinstance(payload, dict):
        raise InvalidResponse()
    identifier = optional_text(payload, "id", limit=100)
    if not valid_provider_id(identifier):
        raise InvalidResponse()
    return Company(
        identifier, optional_text(payload, "name"), optional_text(payload, "ticker", limit=50)
    )


def normalize_fundamental(payload, company_id, statement_code, fiscal_year, fiscal_period):
    if not isinstance(payload, dict):
        raise InvalidResponse()
    identifier = optional_text(payload, "id", limit=100)
    if not valid_provider_id(identifier):
        raise InvalidResponse()
    company = normalize_company(payload.get("company"))
    year = payload.get("fiscal_year")
    if isinstance(year, bool) or not isinstance(year, (int, Decimal)) or year != fiscal_year:
        raise InvalidResponse()
    if (
        company.id != company_id
        or payload.get("statement_code") != statement_code
        or payload.get("fiscal_period") != fiscal_period
    ):
        raise InvalidResponse()
    kind = optional_text(payload, "type", limit=32)
    if kind not in {None, "reported", "calculated", "restated"}:
        raise InvalidResponse()
    start, end = _date_field(payload, "start_date"), _date_field(payload, "end_date")
    if start is not None and end is not None and start > end:
        raise InvalidResponse()
    if any(value is not None and value > datetime.now(UTC).date() for value in (start, end)):
        raise InvalidResponse()
    return Fundamental(
        identifier,
        company,
        statement_code,
        fiscal_year,
        fiscal_period,
        kind,
        start,
        end,
        _timestamp_field(payload, "filing_date"),
        _timestamp_field(payload, "updated_date"),
        _timestamp_field(payload, "first_calculable"),
    )


def _number(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise InvalidResponse()
    number = Decimal(value)
    # Financial losses and cash outflows can be negative. Bound HTML expansion,
    # not the sign, and retain exact JSON decimals without rounding to floats.
    if (
        not number.is_finite()
        or number.copy_abs() > Decimal("1e24")
        or not -18 <= number.as_tuple().exponent <= 24
        or len(number.as_tuple().digits) > 40
    ):
        raise InvalidResponse()
    return number


def normalize_financial_values(payload):
    if not isinstance(payload, list) or len(payload) > MAX_FINANCIAL_ROWS:
        raise InvalidResponse()
    values = []
    tags = set()
    for item in payload:
        if not isinstance(item, dict) or not isinstance(item.get("data_tag"), dict):
            raise InvalidResponse()
        tag = item["data_tag"]
        code = optional_text(tag, "tag", limit=100)
        if (
            code is None
            or re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,99}", code) is None
            or code in tags
        ):
            raise InvalidResponse()
        tags.add(code)
        sequence = _number(tag.get("sequence"))
        if sequence is not None and sequence.copy_abs() > 1_000_000:
            raise InvalidResponse()
        values.append(
            FinancialValue(
                code,
                optional_text(tag, "name"),
                optional_text(tag, "unit", limit=64),
                _number(item.get("value")),
                sequence,
            )
        )
    # Provider order is not assumed. Unknown sequence values remain after known ones.
    return tuple(sorted(values, key=lambda row: (row.sequence is None, row.sequence or 0, row.tag)))
