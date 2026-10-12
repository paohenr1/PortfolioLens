"""Validate dated company-level market cap without reconstructing vendor inputs.

The historical endpoint omits unit metadata, so validate the separate tag record.
An observation date is not evidence of the underlying price/share-count dates.
"""

import re
from datetime import UTC, date, datetime
from decimal import Decimal

from market_data.contracts import Company, CompanyMarketCapitalization
from market_data.errors import InvalidResponse
from market_data.fields import optional_text, valid_provider_id


def validate_market_cap_tag(tag_metadata):
    if (
        not isinstance(tag_metadata, dict)
        or tag_metadata.get("tag") != "marketcap"
        or tag_metadata.get("unit") != "usd"
        or tag_metadata.get("statement_code") != "calculations"
        or tag_metadata.get("type") != "valuation"
    ):
        raise InvalidResponse()


def normalize_market_cap(payload, tag_metadata, security, valuation_date):
    validate_market_cap_tag(tag_metadata)
    if (
        not valid_provider_id(security.company_id)
        or not isinstance(payload, dict)
        or not isinstance(payload.get("company"), dict)
    ):
        raise InvalidResponse()
    company = payload["company"]
    if company.get("id") != security.company_id:
        raise InvalidResponse()
    rows = payload.get("historical_data")
    if not isinstance(rows, list) or len(rows) > 2:
        raise InvalidResponse()
    # One exact date cannot have two competing observations, even if equal.
    if len(rows) > 1:
        raise InvalidResponse()
    value = None
    if rows:
        row = rows[0]
        if not isinstance(row, dict):
            raise InvalidResponse()
        raw_date = row.get("date")
        if not isinstance(raw_date, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_date) is None:
            raise InvalidResponse()
        try:
            observed_date = date.fromisoformat(raw_date)
        except ValueError:
            raise InvalidResponse() from None
        if observed_date != valuation_date:
            raise InvalidResponse()
        value = row.get("value")
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
                raise InvalidResponse()
            value = Decimal(value)
            if (
                not value.is_finite()
                or not 0 <= value <= Decimal("1e24")
                or not -18 <= value.as_tuple().exponent <= 24
                or len(value.as_tuple().digits) > 40
            ):
                raise InvalidResponse()
    cursor = optional_text(payload, "next_page", limit=1024)
    # Empty/whitespace cursors are malformed rather than proof of completion.
    if payload.get("next_page") is not None and cursor is None:
        raise InvalidResponse()
    return CompanyMarketCapitalization(
        security=security,
        company=Company(
            security.company_id,
            optional_text(company, "name"),
            optional_text(company, "ticker", limit=50),
        ),
        valuation_date=valuation_date,
        value=value,
        unit=tag_metadata["unit"],
        source_tag=tag_metadata["tag"],
        retrieved_at=datetime.now(UTC),
        pagination_complete=cursor is None,
        observation_present=bool(rows),
    )
