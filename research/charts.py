"""Price presentation in Python; SVG coordinates never become accounting inputs."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from market_data.contracts import PriceHistory


def price_text(value: Decimal | None) -> str:
    if value is None:
        return "Unavailable"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


@dataclass(frozen=True)
class ChartPoint:
    date: date
    value: str
    x: str
    y: str


@dataclass(frozen=True)
class PriceRow:
    date: date
    close: str
    adjusted_close: str
    period_status: str


@dataclass(frozen=True)
class PriceChart:
    basis_label: str
    points: tuple[ChartPoint, ...]
    paths: tuple[str, ...]
    rows: tuple[PriceRow, ...]
    y_ticks: tuple[tuple[str, str], ...]
    latest: ChartPoint | None
    missing_count: int
    unconfirmed_count: int


def build_price_chart(history: PriceHistory, basis: str) -> PriceChart:
    if basis not in {"raw", "adjusted"}:
        raise ValueError("Unsupported price basis.")
    selected = []
    rows = []
    missing_count = 0
    unconfirmed_count = 0
    for observation in history.observations:
        value = observation.close if basis == "raw" else observation.adjusted_close
        if value is None:
            missing_count += 1
        if observation.intraperiod is not False:
            unconfirmed_count += 1
        # A supplied intraperiod close is not an official daily close.
        selected.append((observation.date, value if observation.intraperiod is False else None))
        rows.append(
            PriceRow(
                date=observation.date,
                close=price_text(observation.close),
                adjusted_close=price_text(observation.adjusted_close),
                period_status=(
                    "Completed"
                    if observation.intraperiod is False
                    else "Incomplete period"
                    if observation.intraperiod is True
                    else "Period status unavailable"
                ),
            )
        )
    values = [value for _, value in selected if value is not None]
    points, paths, ticks = [], [], []
    if values:
        lower, upper = min(values), max(values)
        # Padding keeps a constant or zero series visible without dividing by zero.
        padding = (upper - lower) / 10 if upper != lower else max(abs(lower) / 20, Decimal(1))
        lower, upper = max(Decimal(0), lower - padding), upper + padding
        width, height, left, top = Decimal(780), Decimal(270), Decimal(95), Decimal(20)
        span = Decimal(max(1, (history.end_date - history.start_date).days))
        segment = []
        for observation_date, value in selected:
            if value is None:
                if segment:
                    paths.append(" ".join(segment))
                    segment = []
                continue
            x = left + width * Decimal((observation_date - history.start_date).days) / span
            y = top + height * (upper - value) / (upper - lower)
            point = ChartPoint(observation_date, price_text(value), f"{x:.3f}", f"{y:.3f}")
            points.append(point)
            segment.append(f"{'M' if not segment else 'L'} {point.x} {point.y}")
        if segment:
            paths.append(" ".join(segment))
        for step in range(5):
            value = upper - (upper - lower) * Decimal(step) / 4
            ticks.append((f"{top + height * Decimal(step) / 4:.3f}", f"{value:.4g}"))
    return PriceChart(
        basis_label=("Adjusted close" if basis == "adjusted" else "Raw close"),
        points=tuple(points),
        paths=tuple(paths),
        rows=tuple(reversed(rows)),
        y_ticks=tuple(ticks),
        latest=points[-1] if points else None,
        missing_count=missing_count,
        unconfirmed_count=unconfirmed_count,
    )
