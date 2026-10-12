"""Bounded display coordinates for the already calculated drawdown series."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext


@dataclass(frozen=True)
class ChartPoint:
    as_of: date
    value: Decimal
    x: Decimal
    y: Decimal


def drawdown_chart(summary):
    if summary.issue or not summary.rows:
        return None
    with localcontext() as context:
        context.prec = 64
        scale = max(Decimal("1"), summary.maximum_drawdown_percent)
        start, end = summary.rows[0].as_of, summary.rows[-1].as_of
        points = tuple(
            ChartPoint(
                row.as_of,
                row.drawdown_percent,
                (
                    Decimal(95) + Decimal((row.as_of - start).days) * 780 / (end - start).days
                ).quantize(Decimal("0.01")),
                (Decimal(35) - row.drawdown_percent * 250 / scale).quantize(Decimal("0.01")),
            )
            for row in summary.rows
        )
        return {
            "points": points,
            "path": " ".join(
                f"{'M' if index == 0 else 'L'} {point.x} {point.y}"
                for index, point in enumerate(points)
            ),
            "y_ticks": tuple(
                (y, value.quantize(Decimal("0.01")))
                for y, value in ((35, Decimal(0)), (160, -scale / 2), (285, -scale))
            ),
            "start_date": start,
            "end_date": end,
        }
