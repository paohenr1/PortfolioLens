"""Observed session risk from unrounded returns; no Django, storage or network I/O."""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext
from fractions import Fraction

from ledger.daily_series_math import validated_daily_factors
from ledger.performance import DailySeries, _percent

MIN_VOLATILITY_OBSERVATIONS = 2
MIN_ANNUALIZED_OBSERVATIONS = 20
ANNUAL_SESSIONS = 252
MAX_RISK_OBSERVATIONS = 89  # A 90-calendar-day inclusive window has at most 89 returns.
INCOMPLETE_SERIES = "Risk statistics require a complete valid daily session series."


@dataclass(frozen=True)
class DrawdownPoint:
    as_of: date
    drawdown_percent: Decimal


@dataclass(frozen=True)
class RiskSummary:
    observations: int
    daily_volatility_percent: Decimal | None
    annualized_volatility_percent: Decimal | None
    maximum_drawdown_percent: Decimal | None
    peak_date: date | None
    trough_date: date | None
    recovery_date: date | None
    rows: tuple[DrawdownPoint, ...]
    issue: str | None
    volatility_issue: str | None
    annualization_issue: str | None


def _volatility(variance):
    # Variance remains rational until this square root. Input cent bounds keep
    # per-session returns bounded; a local context avoids caller precision drift.
    with localcontext() as context:
        context.prec = 80
        value = Decimal(variance.numerator) / Decimal(variance.denominator)
        return (value.sqrt() * 100).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def calculate_daily_risk(series):
    """Accept only the consecutive-session producer's DailySeries contract.

    Reconcile all supplied cent values and percentages defensively. No valid
    rows are dropped to manufacture a smaller complete risk sample.
    """
    factors = validated_daily_factors(series)
    observations = (
        len(series.periods)
        if isinstance(series, DailySeries)
        and isinstance(series.periods, tuple)
        and len(series.periods) <= MAX_RISK_OBSERVATIONS
        else 0
    )
    if factors is None:
        return RiskSummary(
            observations, None, None, None, None, None, None, (), INCOMPLETE_SERIES, None, None
        )
    returns = tuple(factor - 1 for factor in factors)
    daily, annualized, volatility_issue, annualization_issue = None, None, None, None
    if observations >= MIN_VOLATILITY_OBSERVATIONS:
        mean = sum(returns, Fraction(0)) / observations
        variance = sum(((value - mean) ** 2 for value in returns), Fraction(0)) / (observations - 1)
        daily = _volatility(variance)
        if observations >= MIN_ANNUALIZED_OBSERVATIONS:
            # Scale the unrounded variance, never a rounded displayed percentage.
            annualized = _volatility(variance * ANNUAL_SESSIONS)
    else:
        volatility_issue = "Daily sample volatility requires at least two session returns."
    if observations < MIN_ANNUALIZED_OBSERVATIONS:
        annualization_issue = "Annualized volatility requires at least twenty session returns."

    wealth, peak, worst = Fraction(1), Fraction(1), Fraction(0)
    last_peak = series.start_date
    episode_peak, trough, recovery, episode_peak_wealth = None, None, None, None
    rows = [DrawdownPoint(series.start_date, Decimal("0.0000"))]
    for row, factor in zip(series.periods, factors, strict=True):
        # This normalized wealth strips external funding. Dollar balances alone
        # would incorrectly report deposits as recovery and withdrawals as losses.
        wealth *= factor
        if wealth >= peak:
            peak, last_peak = wealth, row.end_date
        decline = 1 - wealth / peak
        if decline > worst:
            worst = decline
            episode_peak, trough, recovery = last_peak, row.end_date, None
            episode_peak_wealth = peak
        elif episode_peak_wealth is not None and recovery is None and wealth >= episode_peak_wealth:
            recovery = row.end_date
        rows.append(DrawdownPoint(row.end_date, _percent(wealth / peak)))
    maximum = _percent(1 - worst).copy_negate() if worst else Decimal("0.0000")
    return RiskSummary(
        observations,
        daily,
        annualized,
        maximum,
        episode_peak,
        trough,
        recovery,
        tuple(rows),
        None,
        volatility_issue,
        annualization_issue,
    )
