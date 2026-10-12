import uuid
from zoneinfo import ZoneInfo

from django import forms
from django.utils import timezone

from ledger.domain import KINDS, ZERO, EventInput, LedgerRuleError
from market_data.fields import valid_provider_id


def ledger_today():
    return timezone.localdate(timezone=ZoneInfo("America/Toronto"))


class EntryForm(forms.Form):
    currency = forms.ChoiceField(
        choices=(("USD", "USD — U.S. dollar"),), label="Transaction currency"
    )
    kind = forms.ChoiceField(
        choices=[(value, value.title()) for value in KINDS],
        label="Transaction type",
    )
    event_date = forms.DateField(
        label="Transaction date",
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="Your transaction date, through today in Toronto time.",
    )
    sequence = forms.IntegerField(
        min_value=1,
        max_value=999999,
        label="Same-day order",
        help_text="Explicit order within this date: 1, 2, 3… Each number can be used once.",
    )
    amount = forms.DecimalField(
        max_digits=15,
        decimal_places=2,
        required=False,
        label="Cash amount (USD)",
        help_text="Cash movement or net dividend received; leave blank for trades and splits.",
    )
    security_id = forms.CharField(
        max_length=100,
        required=False,
        label="Intrinio security ID",
        help_text="Trades, dividends, and splits: copy the ID from the instrument details page.",
    )
    quantity = forms.DecimalField(
        max_digits=16,
        decimal_places=6,
        required=False,
        label="Share quantity",
        help_text="Trades only; positive, up to six decimal places.",
    )
    unit_price = forms.DecimalField(
        max_digits=16,
        decimal_places=6,
        required=False,
        label="Execution price (USD per share)",
        help_text="Your actual unadjusted execution price, not an adjusted chart price.",
    )
    fees = forms.DecimalField(
        max_digits=15,
        decimal_places=2,
        required=False,
        initial=0,
        label="Trade fees (USD)",
        help_text="Buy/sell fees only. Leave zero for cash movements.",
    )
    client_key = forms.UUIDField(widget=forms.HiddenInput)
    split_new = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=1000000,
        label="Split new shares",
        help_text="Split only: 2 for a 2-for-1 split.",
    )
    split_old = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=1000000,
        label="Split old shares",
        help_text="Split only: 1 for a 2-for-1 split; 10 for a 1-for-10 reverse split.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial.update(
                kind="DEPOSIT", event_date=ledger_today(), sequence=1, client_key=uuid.uuid4()
            )

    def clean(self):
        values = super().clean()
        if self.errors:
            return values
        security_id = values.get("security_id", "")
        if security_id and not valid_provider_id(security_id):
            self.add_error("security_id", "Enter a valid provider security ID.")
            return values
        self.intent = EventInput(
            **{
                key: values[key]
                for key in (
                    "kind",
                    "event_date",
                    "sequence",
                    "amount",
                    "security_id",
                    "quantity",
                    "unit_price",
                )
            },
            fees=values.get("fees") or ZERO,
            currency=values["currency"],
            split_new=values.get("split_new"),
            split_old=values.get("split_old"),
        )
        try:
            self.intent.validate(ledger_today())
        except LedgerRuleError as error:
            raise forms.ValidationError(str(error)) from None
        return values
