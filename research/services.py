"""Bounded provider requests per action; no data caching before licensing checks."""

import hashlib
import threading
import time

from django.conf import settings

from market_data.errors import CredentialsMissing, ProviderError, ProviderRateLimited
from market_data.intrinio import IntrinioClient

CLIENT_REQUESTS_PER_MINUTE = 10
TOTAL_REQUESTS_PER_MINUTE = 30


class _RequestBudget:
    """Bounded per-process counters that cannot be evicted by a general cache."""

    def __init__(self):
        self._lock = threading.Lock()
        self._window = None
        self._total = 0
        self._clients = {}

    def reset(self):
        with self._lock:
            self._window = None
            self._total = 0
            self._clients.clear()

    def reserve(self, client_address: str):
        # A monotonic clock avoids quota resets caused by wall-clock corrections.
        now = int(time.monotonic())
        identity = hashlib.sha256(client_address.encode()).hexdigest()
        with self._lock:
            if now // 60 != self._window:
                self._window = now // 60
                self._total = 0
                self._clients.clear()
            client_count = self._clients.get(identity, 0)
            if (
                self._total >= TOTAL_REQUESTS_PER_MINUTE
                or client_count >= CLIENT_REQUESTS_PER_MINUTE
            ):
                raise ProviderRateLimited(60 - now % 60)
            # Only admitted requests create entries: at most 30 client hashes.
            self._clients[identity] = client_count + 1
            self._total += 1


_request_budget = _RequestBudget()


def _reserve_request(client_address: str):
    if settings.RATE_LIMIT_BACKEND == "postgresql":
        from operations.rate_limits import BudgetUnavailable, reserve

        try:
            retry_after = reserve("market", client_address)
        except BudgetUnavailable:
            raise ProviderError() from None
        if retry_after is not None:
            raise ProviderRateLimited(retry_after)
    else:
        _request_budget.reserve(client_address)


def _key_and_budget(client_address: str) -> str:
    key = settings.INTRINIO_API_KEY
    if not key:
        raise CredentialsMissing()
    _reserve_request(client_address)
    return key


def search_securities(query: str, client_address: str):
    with IntrinioClient(_key_and_budget(client_address)) as provider:
        return provider.search(query)


def security_details(security_id: str, client_address: str):
    with IntrinioClient(_key_and_budget(client_address)) as provider:
        return provider.security(security_id)


def historical_prices(security_id, start_date, end_date, client_address):
    key = settings.INTRINIO_API_KEY
    if not key:
        raise CredentialsMissing()
    with IntrinioClient(key) as provider:
        return provider.price_history(
            security_id,
            start_date,
            end_date,
            before_request=lambda: _reserve_request(client_address),
        )


def benchmark_prices(security_id, start_date, end_date, client_address):
    """Spend the shared quota on one page, without following a remaining cursor."""
    key = settings.INTRINIO_API_KEY
    if not key:
        raise CredentialsMissing()
    with IntrinioClient(key) as provider:
        return provider.benchmark_prices(
            security_id,
            start_date,
            end_date,
            before_request=lambda: _reserve_request(client_address),
        )


def daily_prices(security_id, price_date, client_address):
    key = settings.INTRINIO_API_KEY
    if not key:
        raise CredentialsMissing()
    with IntrinioClient(key) as provider:
        return provider.daily_prices(
            security_id,
            price_date,
            before_request=lambda: _reserve_request(client_address),
        )


def company_statement(security_id, statement_code, fiscal_year, fiscal_period, client_address):
    key = settings.INTRINIO_API_KEY
    if not key:
        raise CredentialsMissing()
    with IntrinioClient(key) as provider:
        return provider.financial_statement(
            security_id,
            statement_code,
            fiscal_year,
            fiscal_period,
            before_request=lambda: _reserve_request(client_address),
        )


def annual_profitability(security_id, fiscal_year, client_address):
    key = settings.INTRINIO_API_KEY
    if not key:
        raise CredentialsMissing()
    with IntrinioClient(key) as provider:
        return provider.annual_profitability(
            security_id, fiscal_year, before_request=lambda: _reserve_request(client_address)
        )


def annual_growth(security_id, fiscal_year, client_address):
    key = settings.INTRINIO_API_KEY
    if not key:
        raise CredentialsMissing()
    with IntrinioClient(key) as provider:
        return provider.annual_growth(
            security_id, fiscal_year, before_request=lambda: _reserve_request(client_address)
        )


def annual_valuation(security_id, fiscal_year, price_date, client_address):
    key = settings.INTRINIO_API_KEY
    if not key:
        raise CredentialsMissing()
    with IntrinioClient(key) as provider:
        return provider.annual_valuation(
            security_id,
            fiscal_year,
            price_date,
            before_request=lambda: _reserve_request(client_address),
        )


def annual_statement_series(security_id, statement_code, end_year, years, client_address):
    key = settings.INTRINIO_API_KEY
    if not key:
        raise CredentialsMissing()
    with IntrinioClient(key) as provider:
        return provider.annual_statement_series(
            security_id,
            statement_code,
            end_year,
            years,
            before_request=lambda: _reserve_request(client_address),
        )


def market_capitalization(security_id, valuation_date, client_address):
    key = settings.INTRINIO_API_KEY
    if not key:
        raise CredentialsMissing()
    with IntrinioClient(key) as provider:
        return provider.market_capitalization(
            security_id,
            valuation_date,
            before_request=lambda: _reserve_request(client_address),
        )


def market_index_history(key, start_date, end_date, client_address):
    """Exactly one page for a fixed index, sharing the existing admission budget."""
    with IntrinioClient(_key_and_budget(client_address)) as provider:
        return provider.index_history(key, start_date, end_date)
