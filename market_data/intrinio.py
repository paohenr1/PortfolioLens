"""Bounded, backend-only Intrinio reference/price requests with strict normalization."""

import json
import re
import time
from datetime import UTC, date, datetime
from decimal import Decimal
from email.utils import parsedate_to_datetime

import httpx

from market_data.capitalization import normalize_market_cap, validate_market_cap_tag
from market_data.contracts import (
    AnnualGrowthStatements,
    AnnualProfitabilityStatements,
    AnnualStatementSeries,
    AnnualValuationInputs,
    FinancialStatement,
    PriceHistory,
    SearchResult,
    Security,
    SecurityResult,
)
from market_data.errors import (
    AuthenticationFailed,
    CompanyUnavailable,
    CredentialsMissing,
    EntitlementDenied,
    InstrumentNotFound,
    InvalidResponse,
    MarketCapitalizationUnavailable,
    ProviderError,
    ProviderRateLimited,
    StatementUnavailable,
)
from market_data.fields import optional_boolean as _optional_boolean
from market_data.fields import optional_text as _optional_text
from market_data.fields import valid_provider_id as valid_security_id
from market_data.fundamentals import (
    normalize_financial_values,
    normalize_fundamental,
    validate_annual_series_request,
    validate_statement_request,
)
from market_data.prices import (
    MAX_PRICE_DAYS,
    MAX_PRICE_PAGES,
    PRICE_PAGE_SIZE,
    normalize_daily_price,
    validate_price_range,
)

API_BASE = "https://api-v2.intrinio.com"
SEARCH_LIMIT = 20
MAX_RESPONSE_BYTES = 256 * 1024


def normalize_security(payload: object) -> Security:
    if not isinstance(payload, dict):
        raise InvalidResponse()
    identifier = _optional_text(payload, "id", limit=100)
    if identifier is None or not valid_security_id(identifier):
        raise InvalidResponse()
    currency = _optional_text(payload, "currency", limit=3)
    if currency is not None and re.fullmatch(r"[A-Za-z]{3}", currency) is None:
        raise InvalidResponse()
    raw_date = _optional_text(payload, "last_stock_price", limit=10)
    last_price_date = None
    if raw_date is not None:
        try:
            last_price_date = date.fromisoformat(raw_date)
        except ValueError:
            raise InvalidResponse() from None
    company_id = _optional_text(payload, "company_id", limit=100)
    if company_id is not None and not valid_security_id(company_id):
        raise InvalidResponse()
    # The search summary and full reference record use documented field names.
    exchange = (
        _optional_text(payload, "exchange_mic", limit=32)
        or _optional_text(payload, "exchange", limit=32)
        or _optional_text(payload, "listing_exchange_mic", limit=32)
    )
    return Security(
        id=identifier,
        ticker=_optional_text(payload, "ticker", limit=50),
        name=_optional_text(payload, "name"),
        exchange_mic=exchange,
        currency=currency.upper() if currency else None,
        active=_optional_boolean(payload, "active"),
        delisted=_optional_boolean(payload, "delisted"),
        last_stock_price_date=last_price_date,
        company_id=company_id,
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def _reject_nonfinite(value: str):
    raise ValueError("Nonfinite JSON number")


def _retry_after(value: str | None) -> int:
    if value:
        try:
            seconds = int(value)
        except ValueError:
            try:
                timestamp = parsedate_to_datetime(value)
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=UTC)
                seconds = int((timestamp - datetime.now(UTC)).total_seconds())
            except (ValueError, TypeError, OverflowError):
                return 60
        return max(1, min(seconds, 3600))
    return 60


class IntrinioClient:
    def __init__(self, api_key: str, *, transport: httpx.BaseTransport | None = None):
        if not api_key.strip():
            raise CredentialsMissing()
        self._api_key = api_key
        # Retain the platform's HTTPS proxy route, TLS verification, and normal
        # trust configuration. Redirects cannot forward the credential elsewhere.
        self._client = httpx.Client(
            timeout=httpx.Timeout(5.0, connect=3.0),
            follow_redirects=False,
            trust_env=True,
            transport=transport,
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._client.close()

    def _request_json(self, path: str, params: dict | None = None) -> object:
        query = {**(params or {}), "api_key": self._api_key}
        deadline = time.monotonic() + 10
        try:
            with self._client.stream("GET", API_BASE + path, params=query) as response:
                if response.status_code == 401:
                    raise AuthenticationFailed()
                if response.status_code == 403:
                    raise EntitlementDenied()
                if response.status_code == 404:
                    raise InstrumentNotFound()
                if response.status_code == 429:
                    raise ProviderRateLimited(_retry_after(response.headers.get("Retry-After")))
                if response.status_code != 200:
                    raise ProviderError()
                body = bytearray()
                for chunk in response.iter_bytes(chunk_size=4096):
                    if time.monotonic() > deadline:
                        raise ProviderError()
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise InvalidResponse()
            payload = json.loads(
                body,
                parse_float=Decimal,
                parse_constant=_reject_nonfinite,
                object_pairs_hook=_unique_object,
            )
            # Reject credential echoes even in otherwise valid reference records.
            # No provider string should turn an authenticated URL into UI content.
            values = [payload]
            while values:
                value = values.pop()
                if isinstance(value, str) and self._api_key in value:
                    raise InvalidResponse()
                if isinstance(value, dict):
                    values.extend(value.values())
                elif isinstance(value, list):
                    values.extend(value)
            return payload
        except httpx.HTTPError:
            # HTTPX errors can include the authenticated URL. Do not chain them.
            raise ProviderError() from None
        except (ValueError, UnicodeError, RecursionError):
            raise InvalidResponse() from None

    def search(self, query: str) -> SearchResult:
        if not query.strip() or len(query) > 100:
            raise ValueError("Search query must contain 1 to 100 characters.")
        payload = self._request_json(
            "/securities/search", {"query": query, "page_size": SEARCH_LIMIT}
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("securities"), list):
            raise InvalidResponse()
        items = payload["securities"]
        if len(items) > SEARCH_LIMIT:
            raise InvalidResponse()
        securities = tuple(normalize_security(item) for item in items)
        if len({security.id for security in securities}) != len(securities):
            raise InvalidResponse()
        return SearchResult(
            securities=securities,
            retrieved_at=datetime.now(UTC),
            pagination_complete=len(items) < SEARCH_LIMIT and payload.get("next_page") is None,
        )

    def security(self, security_id: str) -> SecurityResult:
        if not valid_security_id(security_id):
            raise ValueError("Invalid security identifier.")
        payload = self._request_json("/securities/" + security_id)
        security = normalize_security(payload)
        if security.id != security_id:
            raise InvalidResponse()
        return SecurityResult(security=security, retrieved_at=datetime.now(UTC))

    def price_history(
        self, security_id: str, start_date: date, end_date: date, *, before_request=None
    ) -> PriceHistory:
        return self._price_history(
            security_id, start_date, end_date, MAX_PRICE_PAGES, before_request
        )

    def daily_prices(self, security_id: str, price_date: date, *, before_request=None):
        """One date, one request. A remaining cursor means the result is incomplete."""
        return self._price_history(security_id, price_date, price_date, 1, before_request)

    def benchmark_prices(self, security_id, start_date, end_date, *, before_request=None):
        """One bounded page; a cursor leaves the comparison explicitly incomplete."""
        validate_price_range(start_date, end_date)
        if (end_date - start_date).days + 1 > 90:
            raise ValueError("Benchmark prices support at most 90 calendar days.")
        return self._price_history(security_id, start_date, end_date, 1, before_request)

    def _price_history(self, security_id, start_date, end_date, page_limit, before_request):
        if not valid_security_id(security_id):
            raise ValueError("Invalid security identifier.")
        validate_price_range(start_date, end_date)
        observations = {}
        security = None
        next_page = None
        seen_tokens = set()
        # Pagination has a fixed request/row bound. Every page spends quota.
        for _ in range(page_limit):
            params = {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "frequency": "daily",
                "page_size": PRICE_PAGE_SIZE,
            }
            if next_page is not None:
                params["next_page"] = next_page
            if before_request is not None:
                before_request()
            payload = self._request_json("/securities/" + security_id + "/prices", params)
            if not isinstance(payload, dict) or not isinstance(payload.get("stock_prices"), list):
                raise InvalidResponse()
            page_security = normalize_security(payload.get("security"))
            if page_security.id != security_id or (
                security is not None
                and (page_security.currency, page_security.exchange_mic)
                != (security.currency, security.exchange_mic)
            ):
                raise InvalidResponse()
            security = security or page_security
            items = payload["stock_prices"]
            if len(items) > PRICE_PAGE_SIZE:
                raise InvalidResponse()
            for item in items:
                observation = normalize_daily_price(item, start_date, end_date)
                if observation.date in observations:
                    raise InvalidResponse()
                observations[observation.date] = observation
            if len(observations) > MAX_PRICE_DAYS:
                raise InvalidResponse()
            # A missing cursor is ambiguous: do not silently claim all pages arrived.
            if "next_page" not in payload:
                raise InvalidResponse()
            next_page = payload["next_page"]
            if next_page is None:
                break
            if (
                not isinstance(next_page, str)
                or not 1 <= len(next_page) <= 1024
                or any(ord(char) < 32 or ord(char) == 127 for char in next_page)
                or next_page in seen_tokens
                or not items
            ):
                raise InvalidResponse()
            seen_tokens.add(next_page)
        return PriceHistory(
            security=security,
            observations=tuple(observations[key] for key in sorted(observations)),
            start_date=start_date,
            end_date=end_date,
            retrieved_at=datetime.now(UTC),
            pagination_complete=next_page is None,
        )

    def financial_statement(
        self, security_id, statement_code, fiscal_year, fiscal_period, *, before_request=None
    ) -> FinancialStatement:
        if not valid_security_id(security_id):
            raise ValueError("Invalid security identifier.")
        validate_statement_request(statement_code, fiscal_year, fiscal_period)

        def request(path):
            if before_request is not None:
                before_request()
            return self._request_json(path)

        security = normalize_security(request("/securities/" + security_id))
        if security.id != security_id:
            raise InvalidResponse()
        if security.company_id is None:
            raise CompanyUnavailable()
        return self._statement_for_security(
            security, statement_code, fiscal_year, fiscal_period, request
        )

    def annual_profitability(self, security_id, fiscal_year, *, before_request=None):
        """One security plus three lookup/value pairs: at most seven requests."""
        if not valid_security_id(security_id):
            raise ValueError("Invalid security identifier.")
        validate_statement_request("income_statement", fiscal_year, "FY")
        validate_statement_request("balance_sheet_statement", fiscal_year - 1, "FY")

        def request(path):
            if before_request is not None:
                before_request()
            return self._request_json(path)

        security = normalize_security(request("/securities/" + security_id))
        if security.id != security_id:
            raise InvalidResponse()
        if security.company_id is None:
            raise CompanyUnavailable()
        # Reuse only this request's verified identity. No cross-request cache,
        # retries, paging, fallback periods or inferred company identities.
        income = self._statement_for_security(
            security, "income_statement", fiscal_year, "FY", request
        )
        opening = self._statement_for_security(
            security, "balance_sheet_statement", fiscal_year - 1, "FY", request
        )
        closing = self._statement_for_security(
            security, "balance_sheet_statement", fiscal_year, "FY", request
        )
        return AnnualProfitabilityStatements(income, opening, closing)

    def annual_growth(self, security_id, fiscal_year, *, before_request=None):
        """One verified security and two annual lookup/value pairs: five requests."""
        if not valid_security_id(security_id):
            raise ValueError("Invalid security identifier.")
        validate_statement_request("income_statement", fiscal_year, "FY")
        validate_statement_request("income_statement", fiscal_year - 1, "FY")

        def request(path):
            if before_request is not None:
                before_request()
            return self._request_json(path)

        security = normalize_security(request("/securities/" + security_id))
        if security.id != security_id:
            raise InvalidResponse()
        if security.company_id is None:
            raise CompanyUnavailable()
        current = self._statement_for_security(
            security, "income_statement", fiscal_year, "FY", request
        )
        prior = self._statement_for_security(
            security, "income_statement", fiscal_year - 1, "FY", request
        )
        return AnnualGrowthStatements(prior, current)

    def annual_valuation(self, security_id, fiscal_year, price_date, *, before_request=None):
        """Explicit FY earnings and a single raw-price date: at most four requests."""
        # Validate both inputs before any reference/statement/price request.
        if not valid_security_id(security_id):
            raise ValueError("Invalid security identifier.")
        validate_statement_request("income_statement", fiscal_year, "FY")
        validate_price_range(price_date, price_date)

        def request(path):
            if before_request is not None:
                before_request()
            return self._request_json(path)

        security = normalize_security(request("/securities/" + security_id))
        if security.id != security_id:
            raise InvalidResponse()
        if security.company_id is None:
            raise CompanyUnavailable()
        income = self._statement_for_security(
            security, "income_statement", fiscal_year, "FY", request
        )
        prices = self.daily_prices(security_id, price_date, before_request=before_request)
        return AnnualValuationInputs(income, prices)

    def market_capitalization(self, security_id, valuation_date, *, before_request=None):
        """Exact-date company observation and explicit USD metadata: three requests."""
        if not valid_security_id(security_id):
            raise ValueError("Invalid security identifier.")
        validate_price_range(valuation_date, valuation_date)

        def request(path, params=None):
            if before_request is not None:
                before_request()
            return self._request_json(path, params)

        security = normalize_security(request("/securities/" + security_id))
        if security.id != security_id:
            raise InvalidResponse()
        if security.company_id is None:
            raise CompanyUnavailable()
        try:
            tag = request("/data_tags/marketcap")
            validate_market_cap_tag(tag)
            payload = request(
                f"/companies/{security.company_id}/historical_data/marketcap",
                {
                    "start_date": valuation_date.isoformat(),
                    "end_date": valuation_date.isoformat(),
                    "frequency": "daily",
                    "page_size": 2,
                    "sort_order": "asc",
                },
            )
        except InstrumentNotFound:
            raise MarketCapitalizationUnavailable() from None
        return normalize_market_cap(payload, tag, security, valuation_date)

    def annual_statement_series(
        self, security_id, statement_code, end_year, years, *, before_request=None
    ):
        """One verified identity and 2–4 lookup/value pairs: five to nine requests."""
        if not valid_security_id(security_id):
            raise ValueError("Invalid security identifier.")
        validate_annual_series_request(statement_code, end_year, years)

        def request(path):
            if before_request is not None:
                before_request()
            return self._request_json(path)

        security = normalize_security(request("/securities/" + security_id))
        if security.id != security_id:
            raise InvalidResponse()
        if security.company_id is None:
            raise CompanyUnavailable()
        # Fetch the explicitly selected years oldest first. A missing requested
        # FY stops the operation; no earlier period or list paging substitutes.
        statements = tuple(
            self._statement_for_security(security, statement_code, year, "FY", request)
            for year in range(end_year - years + 1, end_year + 1)
        )
        return AnnualStatementSeries(statements)

    def _statement_for_security(
        self, security, statement_code, fiscal_year, fiscal_period, request
    ):
        try:
            lookup = normalize_fundamental(
                request(
                    f"/companies/{security.company_id}/fundamentals/lookup/"
                    f"{statement_code}/{fiscal_year}/{fiscal_period}"
                ),
                security.company_id,
                statement_code,
                fiscal_year,
                fiscal_period,
            )
            payload = request("/fundamentals/" + lookup.id + "/standardized_financials")
        except InstrumentNotFound:
            raise StatementUnavailable() from None
        if not isinstance(payload, dict):
            raise InvalidResponse()
        fundamental = normalize_fundamental(
            payload.get("fundamental"),
            security.company_id,
            statement_code,
            fiscal_year,
            fiscal_period,
        )
        # A changed period/date basis between lookup and values cannot be mixed.
        if (
            fundamental.id != lookup.id
            or fundamental.type != lookup.type
            or fundamental.start_date != lookup.start_date
            or fundamental.end_date != lookup.end_date
        ):
            raise InvalidResponse()
        values = normalize_financial_values(payload.get("standardized_financials"))
        # Live responses omit the SDK's optional cursor on this non-paged
        # endpoint. Missing/null means no continuation is indicated, not that
        # every possible metric is available in the supplied statement.
        cursor = payload.get("next_page")
        if cursor is not None and (
            not isinstance(cursor, str)
            or not 1 <= len(cursor) <= 1024
            or any(ord(char) < 32 or ord(char) == 127 for char in cursor)
        ):
            raise InvalidResponse()
        # The SDK exposes no page parameters for this endpoint. Never invent
        # a follow-up URL or silently describe a capped response as complete.
        return FinancialStatement(
            security, fundamental, values, datetime.now(UTC), pagination_complete=cursor is None
        )
