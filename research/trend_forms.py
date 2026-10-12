from django import forms

from market_data.fundamentals import STATEMENTS, validate_annual_series_request


class StatementTrendForm(forms.Form):
    statement = forms.ChoiceField(label="Statement", choices=tuple(STATEMENTS.items()))
    end_year = forms.IntegerField(
        label="Last fiscal year",
        min_value=1901,
        widget=forms.NumberInput(attrs={"inputmode": "numeric"}),
    )
    years = forms.TypedChoiceField(
        label="Annual periods",
        coerce=int,
        choices=((2, "Two FYs"), (3, "Three FYs"), (4, "Four FYs")),
    )

    def clean(self):
        data = super().clean()
        if self.data.get("fiscal_period", "FY") != "FY":
            raise forms.ValidationError("Statement trends support annual FY periods only.")
        if all(key in data for key in ("statement", "end_year", "years")):
            try:
                validate_annual_series_request(data["statement"], data["end_year"], data["years"])
            except ValueError as error:
                raise forms.ValidationError(str(error)) from None
        return data
