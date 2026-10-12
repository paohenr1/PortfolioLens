"""Validate and reconcile exact daily factors without database or calendar I/O."""

from datetime import date
from decimal import Decimal
from fractions import Fraction

from ledger.performance import DailySeries, Subperiod, _money, _percent

MAX_DAILY_OBSERVATIONS = 89


def validated_daily_factors(series):
    if (
        not isinstance(series, DailySeries)
        or series.issue is not None
        or not isinstance(series.periods, tuple)
        or not 1 <= len(series.periods) <= MAX_DAILY_OBSERVATIONS
        or type(series.start_date) is not date
        or type(series.end_date) is not date
        or not date(2000, 1, 1) <= series.start_date < series.end_date
        or (series.end_date - series.start_date).days + 1 > 90
        or not isinstance(series.return_percent, Decimal)
        or not series.return_percent.is_finite()
    ):
        return None
    factors, previous_date, previous_value = [], series.start_date, None
    for row in series.periods:
        if (
            not isinstance(row, Subperiod)
            or row.issue is not None
            or not isinstance(row.return_percent, Decimal)
            or not row.return_percent.is_finite()
        ):
            return None
        start, end, flow, before = (
            _money(row.start_value),
            _money(row.end_value),
            _money(row.external_flow, signed=True),
            _money(row.before_flow_value),
        )
        if (
            type(row.start_date) is not date
            or type(row.end_date) is not date
            or row.start_date != previous_date
            or row.start_date >= row.end_date
            or None in (start, end, flow, before)
            or start <= 0
            or before != end - flow
            or (previous_value is not None and start != previous_value)
        ):
            return None
        factor = before / start
        if row.return_percent != _percent(factor):
            return None
        factors.append(factor)
        previous_date, previous_value = row.end_date, end
    linked = Fraction(1)
    for factor in factors:
        linked *= factor
    if previous_date != series.end_date or series.return_percent != _percent(linked):
        return None
    return tuple(factors)
