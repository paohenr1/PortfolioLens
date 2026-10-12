"""Provider-independent reference data; unknown fields remain explicitly absent."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class Security:
    id: str
    ticker: str | None
    name: str | None
    exchange_mic: str | None
    currency: str | None
    active: bool | None = None
    delisted: bool | None = None
    last_stock_price_date: date | None = None
    company_id: str | None = None


@dataclass(frozen=True)
class SearchResult:
    securities: tuple[Security, ...]
    retrieved_at: datetime


@dataclass(frozen=True)
class SecurityResult:
    security: Security
    retrieved_at: datetime


@dataclass(frozen=True)
class DailyPrice:
    date: date
    close: Decimal | None
    adjusted_close: Decimal | None
    intraperiod: bool | None
    # Optional fields preserve price-only coverage and existing accounting callers.
    volume: Decimal | None = None
    adjusted_volume: Decimal | None = None


@dataclass(frozen=True)
class PriceHistory:
    security: Security
    observations: tuple[DailyPrice, ...]
    start_date: date
    end_date: date
    retrieved_at: datetime
    pagination_complete: bool


@dataclass(frozen=True)
class Company:
    id: str
    name: str | None
    ticker: str | None


@dataclass(frozen=True)
class Fundamental:
    id: str
    company: Company
    statement_code: str
    fiscal_year: int
    fiscal_period: str
    type: str | None
    start_date: date | None
    end_date: date | None
    filing_date: date | datetime | None
    updated_date: date | datetime | None
    first_calculable: date | datetime | None


@dataclass(frozen=True)
class FinancialValue:
    tag: str
    name: str | None
    unit: str | None
    value: Decimal | None
    sequence: Decimal | None


@dataclass(frozen=True)
class FinancialStatement:
    security: Security
    fundamental: Fundamental
    values: tuple[FinancialValue, ...]
    retrieved_at: datetime
    pagination_complete: bool


@dataclass(frozen=True)
class AnnualProfitabilityStatements:
    income: FinancialStatement
    opening_balance: FinancialStatement
    closing_balance: FinancialStatement


@dataclass(frozen=True)
class AnnualGrowthStatements:
    prior: FinancialStatement
    current: FinancialStatement


@dataclass(frozen=True)
class AnnualValuationInputs:
    income: FinancialStatement
    prices: PriceHistory


@dataclass(frozen=True)
class AnnualStatementSeries:
    statements: tuple[FinancialStatement, ...]


@dataclass(frozen=True)
class CompanyMarketCapitalization:
    security: Security
    company: Company
    valuation_date: date
    value: Decimal | None
    unit: str
    source_tag: str
    retrieved_at: datetime
    pagination_complete: bool
    observation_present: bool


class FundamentalsProvider(Protocol):
    def financial_statement(
        self, security_id: str, statement_code: str, fiscal_year: int, fiscal_period: str
    ) -> FinancialStatement: ...


class HistoricalPriceProvider(Protocol):
    def price_history(self, security_id: str, start_date: date, end_date: date) -> PriceHistory: ...


class ReferenceDataProvider(Protocol):
    def search(self, query: str) -> SearchResult: ...

    def security(self, security_id: str) -> SecurityResult: ...
