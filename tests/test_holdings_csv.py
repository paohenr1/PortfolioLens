"""Independent input cases: all-or-nothing CSV validation without Django or provider I/O."""

from datetime import date
from decimal import Decimal, localcontext
from io import BytesIO
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from portfolios.holdings_csv import MAX_CSV_BYTES, parse_holdings_csv
from portfolios.holdings_forms import HoldingsPreviewForm

HEADER = b"ticker,exchange_mic,quantity,currency\n"
VALID = HEADER + b"TSTF,XNAS,1.000001,USD\n"


def upload(content=VALID):
    return SimpleUploadedFile("holdings.csv", content, "text/csv")


class HoldingsCsvTests(SimpleTestCase):
    def parse(self, data):
        return parse_holdings_csv(BytesIO(data))

    def test_bom_crlf_spaces_and_punctuation_preserve_exact_inputs(self):
        result = self.parse(
            b"\xef\xbb\xbfticker,exchange_mic,quantity,currency\r\n"
            b'" TSTF.A ", XNAS , 0.000001 , USD \r\nTst-B,XNYS,1000000000,USD\r\n'
        )
        self.assertFalse(result.issues)
        self.assertEqual(
            [(r.ticker, r.quantity, r.row) for r in result.holdings],
            [("TSTF.A", Decimal("0.000001"), 2), ("Tst-B", Decimal("1000000000"), 3)],
        )

    def test_decimal_input_is_independent_of_callers_precision(self):
        with localcontext() as ctx:
            ctx.prec = 2
            result = self.parse(HEADER + b"TSTF,XNAS,999999999.123456,USD\n")
        self.assertEqual(result.holdings[0].quantity, Decimal("999999999.123456"))

    def test_invalid_numeric_spellings_never_round_or_coerce(self):
        for quantity in (
            "0",
            "-1",
            "+1",
            "1e2",
            "NaN",
            "Infinity",
            ".5",
            "1.",
            "1.0000000",
            "1000000000.000001",
            "1,000",
            "=1+1",
            "١",
            "1" * 200,
        ):
            with self.subTest(quantity=quantity):
                result = self.parse(HEADER + f'TSTF,XNAS,"{quantity}",USD\n'.encode())
                self.assertTrue(result.issues)
                self.assertFalse(result.holdings)

    def test_header_schema_and_encoding_fail_closed(self):
        for data in (
            b"",
            b"ticker,quantity,exchange_mic,currency\n",
            b"ticker;exchange_mic;quantity;currency\n",
            HEADER + b"TSTF,XNAS,1,USD,extra\n",
            HEADER + b"TSTF,XNAS,1\n",
            HEADER + b"\xff,XNAS,1,USD\n",
            HEADER + b'"TSTF,XNAS,1,USD\n',
            HEADER + HEADER,
        ):
            with self.subTest(data=data):
                self.assertTrue(self.parse(data).issues)

    def test_quoted_empty_record_is_not_silently_discarded_as_a_blank_line(self):
        for record in (b'""\n', b'"   "\n', b",,,\n"):
            with self.subTest(record=record):
                self.assertTrue(self.parse(HEADER + record).issues)

    def test_field_errors_are_collected_without_echoing_private_values(self):
        result = self.parse(HEADER + b"=private,XBAD,0,EUR\n")
        self.assertEqual(
            {i.field for i in result.issues}, {"Ticker", "Exchange MIC", "Quantity", "Currency"}
        )
        self.assertTrue(all(i.row == 2 for i in result.issues))
        self.assertNotIn("private", str(result.issues))

    def test_controls_quotes_and_formulas_are_rejected(self):
        for ticker in ("=SUM(1)", "+1", "-1", "@TSTF", 'TS"TF', "TSTF\x00", "\tTSTF", "TSTF\u202e"):
            with self.subTest(ticker=ticker):
                self.assertTrue(self.parse(HEADER + f"{ticker},XNAS,1,USD\n".encode()).issues)
        self.assertTrue(self.parse(HEADER + b'"TS\nTF",XNAS,1,USD\n').issues)
        self.assertTrue(self.parse(b"\t\n" + HEADER).issues)

    def test_duplicate_pair_and_bad_row_do_not_return_partial_holdings(self):
        for second in (b"TSTF,XNAS,2,USD\n", b"OTHER,XNAS,0,USD\n"):
            result = self.parse(VALID + second)
            self.assertFalse(result.holdings)
            self.assertTrue(result.issues)
        self.assertFalse(self.parse(VALID + b"TSTF,XNYS,2,USD\n").issues)

    def test_row_limit_also_counts_invalid_control_rows(self):
        for row in (b"TSTF,XNAS,1,USD\n", b"TSTF\x00,XNAS,1,USD\n"):
            result = self.parse(HEADER + row * 6)
            self.assertIn("five", result.issues[0].message)
            self.assertEqual(len(result.issues), 1)
        self.assertFalse(self.parse(HEADER + b"\n  \n").issues)
        five = HEADER + b"".join(f"TST{i},XNAS,1,USD\n".encode() for i in range(5))
        self.assertEqual(len(self.parse(five).holdings), 5)

    def test_byte_limit_is_inclusive_and_bounded_read_does_not_trust_size(self):
        exact = HEADER + b"\n" * (MAX_CSV_BYTES - len(HEADER))
        self.assertFalse(self.parse(exact).issues)
        self.assertIn("16 KiB", self.parse(exact + b"\n").issues[0].message)
        stream = BytesIO(b"x" * (MAX_CSV_BYTES * 4))
        self.assertTrue(parse_holdings_csv(stream).issues)
        self.assertEqual(stream.tell(), MAX_CSV_BYTES + 1)


class HoldingsMetadataTests(SimpleTestCase):
    def form(self, content=VALID, **changes):
        data = {"name": "Snapshot", "as_of": "2020-01-02", "cash": "0", **changes}
        with patch("portfolios.holdings_forms.ledger_today", return_value=date(2026, 10, 17)):
            form = HoldingsPreviewForm(data, {"holdings_file": upload(content)})
            form.is_valid()
        return form

    def test_zero_cash_and_fractional_shares_are_preserved(self):
        form = self.form()
        self.assertFalse(form.errors)
        self.assertEqual(form.cleaned_data["cash"], Decimal("0"))
        self.assertEqual(form.cleaned_data["holdings_file"][0].quantity, Decimal("1.000001"))

    def test_cash_requires_explicit_plain_decimal_within_bounds(self):
        for cash in ("", "-0", "+0", "1e2", "NaN", "1.001", "1000000000000.01", "1\t", "0" * 33):
            with self.subTest(cash=cash):
                self.assertIn("cash", self.form(cash=cash).errors)
        self.assertFalse(self.form(cash="1000000000000.00").errors)

    def test_empty_holdings_require_positive_cash(self):
        self.assertIn("cash", self.form(content=HEADER, cash="0").errors)
        form = self.form(content=HEADER, cash="0.01")
        self.assertFalse(form.errors)
        self.assertEqual(form.cleaned_data["holdings_file"], ())

    def test_dates_require_completed_sessions_including_exceptional_closures(self):
        for day in (
            "1999-12-31",
            "2026-10-17",
            "2026-10-18",
            "2020-01-04",
            "2020-01-01",
            "2001-09-11",
            "2025-01-09",
            "01/02/2020",
            "",
        ):
            with self.subTest(day=day):
                self.assertIn("as_of", self.form(as_of=day).errors)
        self.assertFalse(self.form(as_of="2020-11-27").errors)  # Short session is valid.

    def test_name_and_multiple_metadata_errors_do_not_hide_csv_errors(self):
        form = self.form(content=HEADER + b"TSTF,XNAS,0,USD\n", name="bad\x00", cash="", as_of="")
        self.assertEqual(set(form.errors), {"name", "cash", "as_of", "holdings_file"})
        self.assertTrue(form.csv_issues)
        self.assertIn("name", self.form(name=" ").errors)
        self.assertIn("name", self.form(name="x" * 101).errors)
