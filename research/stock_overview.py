"""Bounded, independently available price and financial sections for a verified listing."""

import logging
from datetime import UTC, datetime, timedelta

from market_data.errors import (
    AuthenticationFailed,
    CredentialsMissing,
    InvalidResponse,
    ProviderError,
    ProviderRateLimited,
)
from research import services
from research.charts import build_price_chart
from research.fundamentals import statement_presentation

logger = logging.getLogger("research")


def overview_sections(security, client_address):
    today = datetime.now(UTC).date()
    end = today - timedelta(days=1)
    year = today.year - 1
    context = {"overview_fiscal_year": year}
    try:
        history = services.overview_prices(
            security.id, end - timedelta(days=89), end, client_address
        )
        if (history.security.currency, history.security.exchange_mic) != (
            security.currency,
            security.exchange_mic,
        ):
            raise InvalidResponse()
        context.update(history=history, chart=build_price_chart(history, "raw"))
    except ProviderError as error:
        context["price_error"] = error.message
        if isinstance(error, (AuthenticationFailed, CredentialsMissing, ProviderRateLimited)):
            context["financial_error"] = error.message
            return context
    except Exception:
        logger.error("Unexpected overview price failure")
        context["price_error"] = ProviderError.message

    if security.company_id is None:
        context["financial_error"] = "Company financials are unavailable for this listing."
        return context
    try:
        statement = services.overview_income_statement(security, year, client_address)
        context.update(statement=statement, metrics=statement_presentation(statement)["metrics"])
    except ProviderError as error:
        context["financial_error"] = error.message
    except Exception:
        logger.error("Unexpected overview financial statement failure")
        context["financial_error"] = ProviderError.message
    return context
