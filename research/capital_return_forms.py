from django import forms

from market_data.fundamentals import validate_statement_request


class CapitalReturnForm(forms.Form):
    fiscal_year = forms.IntegerField(
        label="Fiscal year",
        min_value=1901,
        widget=forms.NumberInput(attrs={"inputmode": "numeric"}),
        help_text=(
            "Annual FY income and current/preceding FY balance sheets; data loads on submission."
        ),
    )

    def clean_fiscal_year(self):
        year = self.cleaned_data["fiscal_year"]
        try:
            validate_statement_request("income_statement", year, "FY")
            validate_statement_request("balance_sheet_statement", year - 1, "FY")
        except ValueError as error:
            raise forms.ValidationError(str(error)) from None
        return year

    def clean(self):
        data = super().clean()
        if self.data.get("fiscal_period", "FY") != "FY":
            raise forms.ValidationError("This calculation supports annual FY periods only.")
        return data
