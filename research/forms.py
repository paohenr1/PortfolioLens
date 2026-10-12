from django import forms

from market_data.fundamentals import PERIODS, STATEMENTS, validate_statement_request
from market_data.prices import validate_price_range


class SearchForm(forms.Form):
    q = forms.CharField(
        label="Ticker or company name",
        max_length=100,
        strip=True,
        widget=forms.TextInput(
            attrs={"placeholder": "Enter a ticker or company name", "autocomplete": "off"}
        ),
    )

    def clean_q(self):
        query = self.cleaned_data["q"]
        if any(ord(character) < 32 or ord(character) == 127 for character in query):
            raise forms.ValidationError(
                "Enter a ticker or company name without control characters."
            )
        return query


class PriceHistoryForm(forms.Form):
    start_date = forms.DateField(
        label="Start date",
        input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    end_date = forms.DateField(
        label="End date",
        input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    basis = forms.ChoiceField(
        label="Price basis",
        choices=[
            ("adjusted", "Adjusted close (splits and dividends)"),
            ("raw", "Raw close (unadjusted)"),
        ],
    )
    volume_basis = forms.ChoiceField(
        label="Volume basis",
        required=False,
        choices=[
            ("raw", "Raw volume (shares traded)"),
            ("adjusted", "Adjusted volume (provider supplied)"),
        ],
    )

    def clean_volume_basis(self):
        # Older saved price URLs remain usable without adding another request.
        return self.cleaned_data["volume_basis"] or "raw"

    def clean(self):
        data = super().clean()
        if "start_date" in data and "end_date" in data:
            try:
                validate_price_range(data["start_date"], data["end_date"])
            except ValueError as error:
                raise forms.ValidationError(str(error)) from None
        return data


class StatementForm(forms.Form):
    statement_code = forms.ChoiceField(label="Statement", choices=list(STATEMENTS.items()))
    fiscal_year = forms.IntegerField(
        label="Fiscal year",
        min_value=1900,
        widget=forms.NumberInput(attrs={"inputmode": "numeric"}),
    )
    fiscal_period = forms.ChoiceField(label="Fiscal period", choices=list(PERIODS.items()))

    def clean(self):
        data = super().clean()
        if all(field in data for field in ("statement_code", "fiscal_year", "fiscal_period")):
            try:
                validate_statement_request(
                    data["statement_code"], data["fiscal_year"], data["fiscal_period"]
                )
            except ValueError as error:
                raise forms.ValidationError(str(error)) from None
        return data
