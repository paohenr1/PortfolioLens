"""Bounded, provider-independent holdings CSV validation; no persistence or pricing."""

import csv
import io
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from typing import BinaryIO

from market_data.venues import SUPPORTED_MICS

MAX_CSV_BYTES = 16 * 1024
MAX_HOLDINGS = 5
HEADER = ("ticker", "exchange_mic", "quantity", "currency")
PLAIN_DECIMAL = re.compile(r"[0-9]+(?:\.[0-9]+)?")


def has_control(value: str) -> bool:
    return any(unicodedata.category(char).startswith("C") for char in value)


def parse_decimal(value: str, *, places: int, maximum: Decimal, positive: bool) -> Decimal:
    """Validate text before Decimal conversion; never round an input into validity."""
    value = value.strip()
    if len(value) > 32 or not PLAIN_DECIMAL.fullmatch(value):
        raise ValueError("Use plain decimal digits, without signs, exponents or separators.")
    if "." in value and len(value.split(".")[1]) > places:
        raise ValueError(f"Use at most {places} decimal places.")
    number = Decimal(value)
    if number > maximum or (positive and number == 0):
        raise ValueError(f"Enter {'more than' if positive else 'at least'} zero, up to {maximum}.")
    return number


@dataclass(frozen=True)
class HoldingInput:
    row: int
    ticker: str
    exchange_mic: str
    quantity: Decimal
    currency: str


@dataclass(frozen=True)
class CsvIssue:
    row: int
    field: str
    message: str


@dataclass(frozen=True)
class CsvPreview:
    holdings: tuple[HoldingInput, ...]
    issues: tuple[CsvIssue, ...]


def parse_holdings_csv(stream: BinaryIO) -> CsvPreview:
    # A caller-independent cap also protects non-HTTP uses of the parser.
    data = stream.read(MAX_CSV_BYTES + 1)
    if len(data) > MAX_CSV_BYTES:
        return CsvPreview((), (CsvIssue(0, "File", "Use a CSV no larger than 16 KiB."),))
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return CsvPreview(
            (), (CsvIssue(0, "File", "Use UTF-8 text (an optional BOM is allowed)."),)
        )
    lines = io.StringIO(text, newline="").readlines()
    reader = csv.reader(lines, strict=True)
    previous_line = 0
    issues, holdings, seen = [], [], set()
    header_seen = False
    row_count = 0
    try:
        for cells in reader:
            row = reader.line_num
            record = "".join(lines[previous_line:row])
            previous_line = row
            if not record.strip(" \r\n"):
                continue
            if header_seen:
                row_count += 1
                if row_count > MAX_HOLDINGS:
                    return CsvPreview(
                        (), (CsvIssue(row, "File", "Use at most five nonblank holdings rows."),)
                    )
            # Check before trimming so tabs and embedded newlines cannot vanish.
            if any(has_control(cell) for cell in cells):
                issues.append(CsvIssue(row, "Row", "Remove control characters from all fields."))
                if not header_seen:
                    return CsvPreview((), tuple(issues))
                continue
            cells = [cell.strip() for cell in cells]
            if not header_seen:
                if tuple(cells) != HEADER:
                    return CsvPreview(
                        (), (CsvIssue(row, "Header", "Use ticker,exchange_mic,quantity,currency."),)
                    )
                header_seen = True
                continue
            if len(cells) != 4:
                issues.append(
                    CsvIssue(row, "Row", "Each holdings row must have exactly four fields.")
                )
                continue
            ticker, mic, quantity, currency = cells
            before = len(issues)
            if (
                not ticker
                or len(ticker) > 32
                or ticker.startswith(("=", "+", "-", "@"))
                or '"' in ticker
            ):
                issues.append(
                    CsvIssue(row, "Ticker", "Use 1–32 characters, without formulas or quotes.")
                )
            if mic not in SUPPORTED_MICS:
                issues.append(CsvIssue(row, "Exchange MIC", "Choose a supported U.S. equity MIC."))
            if currency != "USD":
                issues.append(CsvIssue(row, "Currency", "Use USD explicitly."))
            try:
                units = parse_decimal(
                    quantity, places=6, maximum=Decimal("1000000000"), positive=True
                )
            except ValueError as error:
                issues.append(CsvIssue(row, "Quantity", str(error)))
            key = (ticker, mic)
            if key in seen:
                issues.append(
                    CsvIssue(row, "Ticker / MIC", "Duplicate holding; combine it explicitly.")
                )
            seen.add(key)
            if len(issues) == before:
                holdings.append(HoldingInput(row, ticker, mic, units, currency))
    except csv.Error:
        issues.append(CsvIssue(reader.line_num, "Row", "Malformed CSV quoting or fields."))
    if not header_seen and not issues:
        issues.append(CsvIssue(0, "Header", "Use ticker,exchange_mic,quantity,currency."))
    # Invalid files never expose a subset as an accepted preview.
    return CsvPreview(() if issues else tuple(holdings), tuple(issues))
