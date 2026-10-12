"""Display coordinates only; exact returns come from the comparison calculator."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext


@dataclass(frozen=True)
class ComparisonPoint:
    as_of: date
    portfolio: Decimal
    benchmark: Decimal
    difference: Decimal
    x: Decimal
    y: Decimal
    benchmark_y: Decimal


def comparison_chart(comparison):
    if comparison is None or comparison.issue or not comparison.rows:
        return None
    values = [(comparison.rows[0].start_date, Decimal(0), Decimal(0), Decimal(0))]
    values.extend(
        (
            row.end_date,
            row.portfolio_cumulative_percent,
            row.benchmark_cumulative_percent,
            row.difference_points,
        )
        for row in comparison.rows
    )
    with localcontext() as context:
        context.prec = max(
            80, *(len(value.as_tuple().digits) + 32 for row in values for value in row[1:])
        )
        low = min(value for row in values for value in row[1:3])
        high = max(value for row in values for value in row[1:3])
        if low == high:
            low, high = low - 1, high + 1
        start, end = values[0][0], values[-1][0]
        points = tuple(
            ComparisonPoint(
                day,
                portfolio,
                benchmark,
                difference,
                (Decimal(95) + Decimal((day - start).days) * 780 / (end - start).days).quantize(
                    Decimal("0.01")
                ),
                (Decimal(285) - (portfolio - low) * 250 / (high - low)).quantize(Decimal("0.01")),
                (Decimal(285) - (benchmark - low) * 250 / (high - low)).quantize(Decimal("0.01")),
            )
            for day, portfolio, benchmark, difference in values
        )

        def path(coordinate):
            return " ".join(
                f"{'M' if index == 0 else 'L'} {point.x} {getattr(point, coordinate)}"
                for index, point in enumerate(points)
            )

        return {
            "points": points,
            "path": path("y"),
            "benchmark_path": path("benchmark_y"),
            "y_ticks": tuple(
                (y, value.quantize(Decimal("0.01")))
                for y, value in ((35, high), (160, (high + low) / 2), (285, low))
            ),
            "start_date": start,
            "end_date": end,
        }
