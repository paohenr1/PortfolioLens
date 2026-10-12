"""Complete-window stock price risk; no web framework, storage or provider I/O."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Context, Decimal, localcontext
from fractions import Fraction

import exchange_calendars

from market_data.contracts import DailyPrice, PriceHistory, Security
from market_data.intrinio import valid_security_id
from market_data.prices import MAX_PRICE_DAYS
from market_data.venues import SUPPORTED_MICS

MIN_DATE = date(2000, 1, 1)
ANNUAL_SESSIONS = 252
MIN_ANNUAL_RETURNS = 20


@dataclass(frozen=True)
class StockRiskRow:
    as_of: date
    close: Decimal
    return_percent: Decimal | None
    drawdown_percent: Decimal


@dataclass(frozen=True)
class StockRisk:
    observations: int = 0
    expected_sessions: int | None = None
    daily_volatility_percent: Decimal | None = None
    annualized_volatility_percent: Decimal | None = None
    maximum_drawdown_percent: Decimal | None = None
    peak_date: date | None = None
    trough_date: date | None = None
    recovery_date: date | None = None
    rows: tuple[StockRiskRow, ...] = ()
    issue: str | None = None
    volatility_issue: str | None = None
    annualization_issue: str | None = None


def percent(ratio):
    """Exact fraction to percentage, half up to four places, independent of context."""
    scaled = Fraction(ratio) * 1_000_000
    units, remainder = divmod(abs(scaled.numerator), scaled.denominator)
    units += 2 * remainder >= scaled.denominator
    return Decimal((int(scaled < 0 and units != 0), tuple(map(int, str(units))), -4))


def _volatility(variance):
    # Only the square root is approximate. A fresh context also isolates caller
    # traps/exponent limits; annualization uses variance before display rounding.
    with localcontext(Context(prec=80)):
        value = Decimal(variance.numerator) / Decimal(variance.denominator)
        return (value.sqrt() * 100).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _valid_close(value):
    return (
        isinstance(value, Decimal)
        and value.is_finite()
        and -18 <= value.as_tuple().exponent <= 12
        and len(value.as_tuple().digits) <= 28
        and 0 < value <= Decimal("1e12")
    )


def calculate_stock_risk(history, basis):
    """Require every regular U.S. equity session inside the requested window.

    Weekend/holiday endpoints are allowed: use the first/last session *inside*
    the window, with no preceding fetch. Missing dates never become multi-day
    returns mislabeled as daily. Any invalid row withholds the entire sample.
    """
    if basis not in {"raw", "adjusted"}:
        raise ValueError("Unsupported price basis.")
    if not isinstance(history, PriceHistory) or (
        not isinstance(history.security, Security)
        or not valid_security_id(history.security.id)
        or not isinstance(history.observations, tuple)
        or len(history.observations) > MAX_PRICE_DAYS
        or history.pagination_complete is not True
        or not isinstance(history.retrieved_at, datetime)
        or history.retrieved_at.tzinfo is None
        or history.retrieved_at.utcoffset() is None
    ):
        return StockRisk(issue="Risk requires a complete, verified historical-price response.")
    if history.security.exchange_mic not in SUPPORTED_MICS:
        return StockRisk(issue="Risk currently supports only identified U.S. equity venues.")
    if (
        type(history.start_date) is not date
        or type(history.end_date) is not date
        or not MIN_DATE <= history.start_date <= history.end_date < datetime.now(UTC).date()
        or (history.end_date - history.start_date).days + 1 > MAX_PRICE_DAYS
    ):
        return StockRisk(issue="Risk requires completed dates from 2000, within 366 calendar days.")
    calendar = exchange_calendars.get_calendar(
        "XNYS",
        start=history.start_date - timedelta(days=7),
        end=history.end_date + timedelta(days=7),
    )
    days = tuple(
        point.date() for point in calendar.sessions_in_range(history.start_date, history.end_date)
    )
    if len(days) < 2:
        return StockRisk(expected_sessions=len(days), issue="Risk requires at least two sessions.")
    if (
        any(not isinstance(row, DailyPrice) for row in history.observations)
        or tuple(row.date for row in history.observations) != days
    ):
        return StockRisk(
            expected_sessions=len(days),
            issue="Risk requires every consecutive U.S. equity session in the requested window."
            " Missing, extra, duplicate or unordered dates cannot be dropped or bridged.",
        )
    closes = tuple(
        row.close if basis == "raw" else row.adjusted_close for row in history.observations
    )
    if any(row.intraperiod is not False for row in history.observations) or any(
        not _valid_close(value) for value in closes
    ):
        return StockRisk(
            expected_sessions=len(days),
            issue="Risk requires a confirmed, strictly positive selected close at every session."
            " Missing or zero prices and unconfirmed periods cannot be substituted.",
        )
    # Percentages are dimensionless, so listing currency is not assumed or
    # converted. The adapter has already required consistent metadata across pages.
    prices = tuple(Fraction(value) for value in closes)
    returns = tuple(
        current / prior - 1 for prior, current in zip(prices[:-1], prices[1:], strict=True)
    )
    count = len(returns)
    daily, annualized = None, None
    if count >= 2:
        mean = sum(returns, Fraction(0)) / count
        variance = sum(((value - mean) ** 2 for value in returns), Fraction(0)) / (count - 1)
        daily = _volatility(variance)
        if count >= MIN_ANNUAL_RETURNS:
            annualized = _volatility(variance * ANNUAL_SESSIONS)

    peak, worst, last_peak = prices[0], Fraction(0), days[0]
    episode_peak, trough, recovery, episode_price = None, None, None, None
    rows = []
    for index, (day, price) in enumerate(zip(days, prices, strict=True)):
        if price >= peak:
            peak, last_peak = price, day
        decline = 1 - price / peak
        if decline > worst:
            worst = decline
            episode_peak, trough, recovery, episode_price = last_peak, day, None, peak
        elif episode_price is not None and recovery is None and price >= episode_price:
            recovery = day
        rows.append(
            StockRiskRow(
                day,
                closes[index],
                percent(returns[index - 1]) if index else None,
                percent(-decline),
            )
        )
    return StockRisk(
        observations=count,
        expected_sessions=len(days),
        daily_volatility_percent=daily,
        annualized_volatility_percent=annualized,
        maximum_drawdown_percent=percent(worst),
        peak_date=episode_peak,
        trough_date=trough,
        recovery_date=recovery,
        rows=tuple(rows),
        volatility_issue="Daily sample volatility requires at least two session returns."
        if count < 2
        else None,
        annualization_issue="Annualized volatility requires at least twenty session returns."
        if count < MIN_ANNUAL_RETURNS
        else None,
    )
