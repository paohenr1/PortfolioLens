"""Exact matched-session comparisons; provider-adjusted prices are a proxy basis."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from fractions import Fraction

from ledger.daily_series_math import validated_daily_factors
from ledger.performance import _percent
from ledger.relationships import (
    ReturnRelationship,
    calculate_relationship,
    unavailable_relationship,
)
from market_data.contracts import DailyPrice, PriceHistory, Security, SecurityResult
from market_data.venues import SUPPORTED_MICS

INCOMPLETE_COMPARISON = (
    "Comparison requires complete portfolio returns and confirmed adjusted USD closes "
    "for the benchmark on every matching session."
)


@dataclass(frozen=True)
class ComparisonRow:
    start_date: date
    end_date: date
    adjusted_close: Decimal
    portfolio_return_percent: Decimal
    benchmark_return_percent: Decimal
    portfolio_cumulative_percent: Decimal
    benchmark_cumulative_percent: Decimal
    difference_points: Decimal


@dataclass(frozen=True)
class BenchmarkComparison:
    security_id: str
    reference: SecurityResult | None
    retrieved_at: datetime | None
    portfolio_return_percent: Decimal | None
    benchmark_return_percent: Decimal | None
    difference_points: Decimal | None
    rows: tuple[ComparisonRow, ...]
    issue: str | None
    relationship: ReturnRelationship | None = None


def _aware(value):
    return (
        isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None
    )


def _confirmed_prices(series, reference, history, security_id):
    if (
        not isinstance(reference, SecurityResult)
        or not isinstance(reference.security, Security)
        or not _aware(reference.retrieved_at)
        or reference.security.id != security_id
        or reference.security.currency != "USD"
        or reference.security.exchange_mic not in SUPPORTED_MICS
        or not isinstance(history, PriceHistory)
        or not isinstance(history.security, Security)
        or history.security.id != security_id
        or history.security.currency != "USD"
        or history.security.exchange_mic != reference.security.exchange_mic
        or not _aware(history.retrieved_at)
        or history.start_date != series.start_date
        or history.end_date != series.end_date
        or history.pagination_complete is not True
        or not isinstance(history.observations, tuple)
        or len(history.observations) != len(series.periods) + 1
    ):
        return None
    dates = (series.start_date, *(row.end_date for row in series.periods))
    prices = []
    for day, point in zip(dates, history.observations, strict=True):
        if not isinstance(point, DailyPrice):
            return None
        value = point.adjusted_close
        if (
            type(point.date) is not date
            or point.date != day
            or point.intraperiod is not False
            or not isinstance(value, Decimal)
            or not value.is_finite()
            or not Decimal(0) <= value <= Decimal("1e12")
            or len(value.as_tuple().digits) > 28
            or not -18 <= value.as_tuple().exponent <= 12
        ):
            return None
        prices.append(value)
    # A zero terminal price can represent total loss; a zero opening price
    # cannot define a subsequent return. Never bridge that undefined session.
    return tuple(prices) if all(price > 0 for price in prices[:-1]) else None


def unavailable_comparison(security_id, issue=INCOMPLETE_COMPARISON, reference=None):
    return BenchmarkComparison(
        security_id, reference, None, None, None, None, (), issue, unavailable_relationship()
    )


def calculate_comparison(series, reference, history, security_id):
    """Validate every date and link rational factors before display rounding.

    The return gap is portfolio minus benchmark in percentage points. It is
    neither a relative wealth ratio nor alpha. Portfolio funding is removed by
    its daily producer; the benchmark never receives journal cash flows.
    """
    factors = validated_daily_factors(series)
    if factors is None:
        return unavailable_comparison(security_id)
    prices = _confirmed_prices(series, reference, history, security_id)
    if prices is None:
        return unavailable_comparison(security_id)
    portfolio, benchmark, rows = Fraction(1), Fraction(1), []
    benchmark_factors = []
    for index, (period, factor) in enumerate(zip(series.periods, factors, strict=True), start=1):
        benchmark_factor = Fraction(prices[index]) / Fraction(prices[index - 1])
        benchmark_factors.append(benchmark_factor)
        portfolio *= factor
        benchmark *= benchmark_factor
        rows.append(
            ComparisonRow(
                period.start_date,
                period.end_date,
                prices[index],
                _percent(factor),
                _percent(benchmark_factor),
                _percent(portfolio),
                _percent(benchmark),
                _percent(1 + portfolio - benchmark),
            )
        )
    return BenchmarkComparison(
        security_id,
        reference,
        history.retrieved_at,
        _percent(portfolio),
        _percent(benchmark),
        _percent(1 + portfolio - benchmark),
        tuple(rows),
        None,
        calculate_relationship(factors, tuple(benchmark_factors)),
    )
