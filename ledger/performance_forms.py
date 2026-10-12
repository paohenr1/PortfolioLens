from datetime import date, timedelta

from django import forms

from ledger.forms import ledger_today


class PerformanceForm(forms.Form):
    start_date = forms.DateField(
        label="Opening valuation date", widget=forms.DateInput(attrs={"type": "date"})
    )
    end_date = forms.DateField(
        label="Closing valuation date", widget=forms.DateInput(attrs={"type": "date"})
    )
    timing_checked = forms.BooleanField(
        label="I confirmed that deposits and withdrawals after the opening date occurred "
        "at end of day, after all other activity, and recorded shares match raw closing prices."
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            end = ledger_today() - timedelta(days=1)
            self.initial.update(start_date=end - timedelta(days=30), end_date=end)

    def clean(self):
        values = super().clean()
        start, end = values.get("start_date"), values.get("end_date")
        if (
            start
            and end
            and not (
                date(1900, 1, 1) <= start < end < ledger_today() and (end - start).days + 1 <= 366
            )
        ):
            raise forms.ValidationError(
                "Choose increasing completed dates from 1900, covering at most 366 calendar days."
            )
        return values
