from django import forms

from market_data.fundamentals import validate_statement_request


class AnnualGrowthForm(forms.Form):
    fiscal_year = forms.IntegerField(
        label="Current fiscal year",
        min_value=1901,
        widget=forms.NumberInput(attrs={"inputmode": "numeric"}),
        help_text="Compare annual income for this FY against the immediately preceding FY.",
    )

    def clean_fiscal_year(self):
        year = self.cleaned_data["fiscal_year"]
        try:
            validate_statement_request("income_statement", year, "FY")
            validate_statement_request("income_statement", year - 1, "FY")
        except ValueError as error:
            raise forms.ValidationError(str(error)) from None
        return year

    def clean(self):
        data = super().clean()
        if self.data.get("fiscal_period", "FY") != "FY":
            raise forms.ValidationError("Growth comparisons support annual FY periods only.")
        return data
