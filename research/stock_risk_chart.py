"""Bounded stock drawdown display geometry, never a calculation input."""

from fractions import Fraction

from research.stock_risk import percent


def stock_drawdown_chart(summary):
    if summary.issue or not summary.rows:
        return None
    start, end = summary.rows[0].as_of, summary.rows[-1].as_of
    scale = max(Fraction(1), Fraction(summary.maximum_drawdown_percent))
    points = tuple(
        {
            "as_of": row.as_of,
            "value": row.drawdown_percent,
            "x": 95 + round(Fraction((row.as_of - start).days * 780, (end - start).days)),
            "y": 35 + round(-Fraction(row.drawdown_percent) * 250 / scale),
        }
        for row in summary.rows
    )
    return {
        "points": points,
        "path": " ".join(
            f"{'M' if index == 0 else 'L'} {point['x']} {point['y']}"
            for index, point in enumerate(points)
        ),
        "start_date": start,
        "end_date": end,
        "y_ticks": ((35, "0.0000"), (160, percent(-scale / 200)), (285, percent(-scale / 100))),
    }
