"""Supplied daily share volume, exact values and bounded rational display geometry."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from fractions import Fraction

from research.charts import price_text


@dataclass(frozen=True)
class VolumePoint:
    date: date
    value: str
    x: int
    y: int
    bar_left: int
    height: int


@dataclass(frozen=True)
class VolumeRow:
    date: date
    volume: str
    adjusted_volume: str
    period_status: str


@dataclass(frozen=True)
class VolumeChart:
    basis_label: str
    points: tuple[VolumePoint, ...]
    rows: tuple[VolumeRow, ...]
    latest: VolumePoint | None
    missing_count: int
    unconfirmed_count: int
    scale_label: str
    bar_width: int


def build_volume_chart(history, basis):
    """Plot confirmed supplied observations, without inferring calendar coverage.

    Missing/unconfirmed values have no bar. A known zero has a selectable point
    on the zero baseline. Gaps never become zero bars, cumulative sums or averages.
    """
    if basis not in {"raw", "adjusted"}:
        raise ValueError("Unsupported volume basis.")
    rows, selected, missing, unconfirmed = [], [], 0, 0
    for row in history.observations:
        value = row.volume if basis == "raw" else row.adjusted_volume
        missing += value is None
        unconfirmed += row.intraperiod is not False
        if value is not None and row.intraperiod is False:
            selected.append((row.date, value))
        rows.append(
            VolumeRow(
                row.date,
                price_text(row.volume),
                price_text(row.adjusted_volume),
                "Completed"
                if row.intraperiod is False
                else "Incomplete period"
                if row.intraperiod is True
                else "Period status unavailable",
            )
        )
    maximum = max((value for _, value in selected), default=Decimal(0))
    scale = Fraction(maximum) if maximum else Fraction(1)
    span = max(1, (history.end_date - history.start_date).days)
    # Daily bars retain actual calendar spacing, even for weekend/absent dates.
    # A minimum one-pixel width bounds dense year-long charts without summing rows.
    width = max(1, min(18, 390 // span))
    points = []
    for day, value in selected:
        x = 95 + round(Fraction((day - history.start_date).days * 780, span))
        height = round(Fraction(value) * 250 / scale)
        points.append(VolumePoint(day, price_text(value), x, 285 - height, x - width // 2, height))
    return VolumeChart(
        "Raw volume" if basis == "raw" else "Adjusted volume",
        tuple(points),
        tuple(reversed(rows)),
        points[-1] if points else None,
        missing,
        unconfirmed,
        format(maximum, ".4g") if maximum else "1",
        width,
    )
