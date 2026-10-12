from django import forms

from market_data.fundamentals import validate_statement_request
from market_data.prices import validate_price_range


class AnnualMultipleForm(forms.Form):
    fiscal_year = forms.IntegerField(
        label="Earnings fiscal year",
        min_value=1900,
        widget=forms.NumberInput(attrs={"inputmode": "numeric"}),
        help_text="An explicit annual FY income period, not trailing or forecast earnings.",
    )
    price_date = forms.DateField(
        label="Raw closing price date",
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="Use an exact date on or after the income period end; no prior-day fallback.",
    )
    basis_confirmed = forms.BooleanField(
        label="I confirm the EPS matches this listed share class and the raw price's split basis",
        help_text=(
            "Check share class, ADR ratio and any splits or restatement adjustments. "
            "The company link alone cannot verify this."
        ),
        error_messages={"required": "Confirm share-class and EPS/price split compatibility."},
    )

    def clean_fiscal_year(self):
        year = self.cleaned_data["fiscal_year"]
        try:
            validate_statement_request("income_statement", year, "FY")
        except ValueError as error:
            raise forms.ValidationError(str(error)) from None
        return year

    def clean_price_date(self):
        value = self.cleaned_data["price_date"]
        try:
            validate_price_range(value, value)
        except ValueError as error:
            raise forms.ValidationError(str(error)) from None
        return value

    def clean(self):
        data = super().clean()
        if self.data.get("fiscal_period", "FY") != "FY":
            raise forms.ValidationError("Valuation multiples support annual FY earnings only.")
        return data
