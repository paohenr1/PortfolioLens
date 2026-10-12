"""Exact four-place half-up display rounding for rational coefficients."""

from decimal import Decimal
from math import isqrt


def _coefficient(units, *, negative=False):
    # Bounded analytics inputs keep this digit string small. Constructing a
    # Decimal tuple bypasses caller precision, exponent limits and traps.
    return Decimal((int(negative and units != 0), tuple(int(x) for x in str(units)), -4))


def rounded_ratio(value):
    units, remainder = divmod(abs(value.numerator) * 10000, value.denominator)
    if 2 * remainder >= value.denominator:
        units += 1
    return _coefficient(units, negative=value < 0)


def rounded_square_root(squared, *, negative=False):
    # Compare against a squared half-unit boundary, avoiding an approximate
    # square root and double rounding near a display tie.
    numerator, denominator = squared.numerator * 10000**2, squared.denominator
    units = isqrt(numerator // denominator)
    if 4 * numerator >= (2 * units + 1) ** 2 * denominator:
        units += 1
    return _coefficient(units, negative=negative)
