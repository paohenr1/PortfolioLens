"""Snapshot metadata and CSV checks only; no reference lookup or saved holdings."""

from datetime import date, timedelta
from decimal import Decimal

import exchange_calendars
from django import forms

from ledger.forms import ledger_today
from portfolios.holdings_csv import has_control, parse_decimal, parse_holdings_csv


class HoldingsMetadataForm(forms.Form):
    name = forms.CharField(max_length=100, label="Snapshot name")
    as_of = forms.DateField(
        label="Holdings as-of date",
        input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="A completed U.S. equity session from 2000 through yesterday in Toronto time.",
    )
    cash = forms.CharField(
        max_length=32,
        label="Cash balance (USD)",
        help_text="Enter zero explicitly if there is no cash; blank does not mean zero.",
    )

    def clean_name(self):
        value = self.cleaned_data["name"]
        if has_control(self.data.get("name", "")):
            raise forms.ValidationError("Enter a name without control characters.")
        return value

    def clean_cash(self):
        raw = self.data.get("cash", "")
        if has_control(raw):
            raise forms.ValidationError("Remove control characters from the cash amount.")
        try:
            return parse_decimal(raw, places=2, maximum=Decimal("1000000000000"), positive=False)
        except ValueError as error:
            raise forms.ValidationError(str(error)) from None

    def clean_as_of(self):
        value = self.cleaned_data["as_of"]
        if not date(2000, 1, 1) <= value < ledger_today():
            raise forms.ValidationError(
                "Choose a date from 2000 through yesterday in Toronto time."
            )
        calendar = exchange_calendars.get_calendar(
            "XNYS", start=value - timedelta(days=7), end=value + timedelta(days=7)
        )
        if not calendar.is_session(value.isoformat()):
            raise forms.ValidationError(
                "Choose a completed U.S. equity session, not a closure date."
            )
        return value


class HoldingsPreviewForm(HoldingsMetadataForm):
    holdings_file = forms.FileField(
        label="Holdings CSV",
        widget=forms.ClearableFileInput(attrs={"accept": ".csv,text/csv"}),
        help_text="UTF-8 CSV, up to 16 KiB and five holdings rows. Select it again after an error.",
    )

    def clean_holdings_file(self):
        result = parse_holdings_csv(self.cleaned_data["holdings_file"])
        self.csv_issues = result.issues
        if result.issues:
            raise forms.ValidationError(
                "Correct the CSV errors listed below and select the file again."
            )
        return result.holdings

    def clean(self):
        data = super().clean()
        if data.get("holdings_file") == () and data.get("cash") == 0:
            self.add_error("cash", "A cash-only file requires a positive cash balance.")
        return data
