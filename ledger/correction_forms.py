"""Separate replacement and void forms keep irrelevant trade fields optional."""

import uuid

from django import forms

from ledger.corrections import validate_reason
from ledger.domain import LedgerRuleError
from ledger.forms import EntryForm


def clean_reason(value):
    try:
        return validate_reason(value)
    except LedgerRuleError as error:
        raise forms.ValidationError(str(error)) from None


class ReplacementForm(EntryForm):
    reason = forms.CharField(label="Correction reason", max_length=500)

    def __init__(self, *args, **kwargs):
        initial = dict(kwargs.get("initial", {}))
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial.update(initial)

    def clean_reason(self):
        return clean_reason(self.cleaned_data["reason"])


class VoidForm(forms.Form):
    reason = forms.CharField(label="Correction reason", max_length=500)
    client_key = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial["client_key"] = uuid.uuid4()

    def clean_reason(self):
        return clean_reason(self.cleaned_data["reason"])


class SaveCorrectionForm(forms.Form):
    preview_token = forms.CharField(max_length=8192, widget=forms.HiddenInput)
    confirmed = forms.BooleanField(
        label="I reviewed this correction and its effect on the journal."
    )
