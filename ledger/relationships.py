"""Observed relationships between exact paired simple returns; no I/O."""

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from ledger.daily_series_math import MAX_DAILY_OBSERVATIONS
from ledger.ratio_math import rounded_ratio, rounded_square_root

MIN_RELATIONSHIP_OBSERVATIONS = 20
INCOMPLETE_RELATIONSHIP = "Relationship statistics require a complete valid matched daily series."


@dataclass(frozen=True)
class ReturnRelationship:
    observations: int
    correlation: Decimal | None
    beta: Decimal | None
    issue: str | None
    correlation_issue: str | None = None


def unavailable_relationship(issue=INCOMPLETE_RELATIONSHIP):
    return ReturnRelationship(0, None, None, issue)


def _valid_factors(values):
    # These bounds exceed factors from the existing money/price contracts and
    # keep direct callers from supplying unbounded rational arithmetic work.
    return (
        isinstance(values, tuple)
        and 1 <= len(values) <= MAX_DAILY_OBSERVATIONS
        and all(
            isinstance(value, Fraction)
            and value.numerator.bit_length() <= 200
            and value.denominator.bit_length() <= 200
            and 0 <= value <= Fraction(10**30)
            for value in values
        )
    )


def calculate_relationship(portfolio_factors, benchmark_factors):
    """Accept exact, date-aligned factors from the validated comparison producer.

    Pearson correlation and OLS beta with an intercept use centered simple
    returns. The sample covariance/variance divisors cancel in these ratios;
    cumulative levels and rounded displayed percentages are never inputs.
    """
    if (
        not _valid_factors(portfolio_factors)
        or not _valid_factors(benchmark_factors)
        or len(portfolio_factors) != len(benchmark_factors)
    ):
        return unavailable_relationship()
    count = len(portfolio_factors)
    if count < MIN_RELATIONSHIP_OBSERVATIONS:
        return ReturnRelationship(
            count,
            None,
            None,
            "Correlation and beta require at least twenty matched session returns.",
        )
    portfolio = tuple(value - 1 for value in portfolio_factors)
    benchmark = tuple(value - 1 for value in benchmark_factors)
    portfolio_mean = sum(portfolio, Fraction(0)) / count
    benchmark_mean = sum(benchmark, Fraction(0)) / count
    centered = tuple(
        (left - portfolio_mean, right - benchmark_mean)
        for left, right in zip(portfolio, benchmark, strict=True)
    )
    portfolio_squares = sum((left * left for left, _ in centered), Fraction(0))
    benchmark_squares = sum((right * right for _, right in centered), Fraction(0))
    if benchmark_squares == 0:
        return ReturnRelationship(
            count,
            None,
            None,
            "Benchmark return variance is zero; correlation and beta are undefined.",
        )
    cross = sum((left * right for left, right in centered), Fraction(0))
    beta = rounded_ratio(cross / benchmark_squares)
    if portfolio_squares == 0:
        # A flat portfolio has a zero slope against a varying benchmark, but no
        # defined correlation: its standard deviation is zero.
        return ReturnRelationship(
            count,
            None,
            beta,
            None,
            "Portfolio return variance is zero; correlation is undefined.",
        )
    return ReturnRelationship(
        count,
        rounded_square_root(
            cross * cross / (portfolio_squares * benchmark_squares), negative=cross < 0
        ),
        beta,
        None,
    )
