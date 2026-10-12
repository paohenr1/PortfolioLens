from datetime import date, timedelta

from django import forms

from ledger.forms import ledger_today


class ValuationForm(forms.Form):
    as_of = forms.DateField(
        label="Valuation date",
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="A completed date in Toronto time; prices must match this exact date.",
    )
    share_basis_checked = forms.BooleanField(
        label="I have recorded relevant transactions and splits through this date and checked "
        "that the shares match the unadjusted price basis.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial["as_of"] = ledger_today() - timedelta(days=1)

    def clean_as_of(self):
        value = self.cleaned_data["as_of"]
        if not date(1900, 1, 1) <= value < ledger_today():
            raise forms.ValidationError(
                "Choose a date from 1900 through yesterday in Toronto time."
            )
        return value
