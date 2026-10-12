"""Observed Sharpe ratios with an explicit constant annual simple-rate assumption."""

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from ledger.daily_series_math import validated_daily_factors
from ledger.performance import _percent
from ledger.ratio_math import rounded_square_root

MIN_SHARPE_OBSERVATIONS = 20
SHARPE_ANNUAL_SESSIONS = 252


@dataclass(frozen=True)
class SharpeSummary:
    observations: int
    annual_risk_free_percent: Decimal | None
    daily_risk_free_percent: Decimal | None
    mean_excess_percent: Decimal | None
    daily_sharpe: Decimal | None
    annualized_sharpe: Decimal | None
    issue: str | None


def calculate_sharpe(series, annual_risk_free_percent):
    """Use exact simple excess returns and sample volatility, never table values.

    The explicit annual simple percentage is divided by 100 and 252. It is
    neither an effective compounded yield nor calendar-day interest accrual.
    """
    rate = annual_risk_free_percent
    if (
        not isinstance(rate, Decimal)
        or not rate.is_finite()
        or not Decimal(-100) <= rate <= Decimal(100)
        or len(rate.as_tuple().digits) > 7
        or not -4 <= rate.as_tuple().exponent <= 2
    ):
        return SharpeSummary(
            0,
            None,
            None,
            None,
            None,
            None,
            "Enter an annual simple risk-free percentage from -100 to 100, "
            "with at most four decimal places.",
        )
    daily_rate = Fraction(rate) / (100 * SHARPE_ANNUAL_SESSIONS)
    daily_percent = _percent(1 + daily_rate)
    factors = validated_daily_factors(series)
    if factors is None:
        return SharpeSummary(
            0,
            rate,
            daily_percent,
            None,
            None,
            None,
            "Sharpe requires a complete valid daily session series.",
        )
    count = len(factors)
    if count < MIN_SHARPE_OBSERVATIONS:
        return SharpeSummary(
            count,
            rate,
            daily_percent,
            None,
            None,
            None,
            "Sharpe requires at least twenty complete session returns.",
        )
    excess = tuple(factor - 1 - daily_rate for factor in factors)
    mean = sum(excess, Fraction(0)) / count
    variance = sum(((value - mean) ** 2 for value in excess), Fraction(0)) / (count - 1)
    if variance == 0:
        # Zero denominator is undefined even for nonzero mean excess return;
        # do not manufacture zero or infinite Sharpe values.
        return SharpeSummary(
            count,
            rate,
            daily_percent,
            _percent(1 + mean),
            None,
            None,
            "Sample excess-return volatility is zero; Sharpe is undefined.",
        )
    squared_ratio = mean * mean / variance
    return SharpeSummary(
        count,
        rate,
        daily_percent,
        _percent(1 + mean),
        rounded_square_root(squared_ratio, negative=mean < 0),
        rounded_square_root(squared_ratio * SHARPE_ANNUAL_SESSIONS, negative=mean < 0),
        None,
    )
