"""Exact selected-period financial arithmetic; no currency/unit assumptions."""

from decimal import Decimal
from fractions import Fraction


def valid_financial_number(value):
    return (
        isinstance(value, Decimal)
        and value.is_finite()
        and -18 <= value.as_tuple().exponent <= 24
        and len(value.as_tuple().digits) <= 40
        and value.copy_abs() <= Decimal("1e24")
    )


def _rounded_ratio(numerator, denominator, scale):
    # Retain exact rational inputs; round only the final result half up.
    ratio = Fraction(numerator) / Fraction(denominator) * scale
    units, remainder = divmod(abs(ratio.numerator) * 100, ratio.denominator)
    units += remainder * 2 >= ratio.denominator
    return Decimal((int(ratio < 0 and units != 0), tuple(map(int, str(units))), -2))


def rounded_percent(numerator, denominator):
    return _rounded_ratio(numerator, denominator, 100)


def rounded_multiple(numerator, denominator):
    """A dimensionless multiple, not a percentage; two places, half up."""
    return _rounded_ratio(numerator, denominator, 1)


def _coefficient_at(value, exponent):
    parts = value.as_tuple()
    return (
        (-1 if parts.sign else 1)
        * int("".join(map(str, parts.digits)))
        * 10 ** (parts.exponent - exponent)
    )


def exact_change(prior: Decimal, current: Decimal) -> Decimal:
    """Current minus prior, without rounding or ambient Decimal arithmetic."""
    exponent = min(prior.as_tuple().exponent, current.as_tuple().exponent)
    units = _coefficient_at(current, exponent) - _coefficient_at(prior, exponent)
    return Decimal((int(units < 0), tuple(map(int, str(abs(units)))), exponent))


def average_balance(opening: Decimal, closing: Decimal) -> Decimal:
    # Two finite Decimal observations have an exact finite mean. Align their
    # integer coefficients instead of depending on ambient Decimal precision.
    exponent = min(opening.as_tuple().exponent, closing.as_tuple().exponent)

    total = _coefficient_at(opening, exponent) + _coefficient_at(closing, exponent)
    if total % 2:
        units, exponent = total * 5, exponent - 1
    else:
        units = total // 2
    return Decimal((int(units < 0), tuple(map(int, str(abs(units)))), exponent))
