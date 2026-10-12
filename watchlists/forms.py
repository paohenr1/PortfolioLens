from django import forms

from market_data.fields import valid_provider_id
from market_data.prices import validate_price_range
from watchlists.market import INSTRUMENT_ORDERS, MAX_MARKET_ITEMS, PRICE_BASES, VOLUME_BASES


class WatchlistForm(forms.Form):
    name = forms.CharField(label="Watchlist name", max_length=100, strip=True)

    def clean_name(self):
        name = self.cleaned_data["name"]
        if any(ord(c) < 32 or ord(c) == 127 for c in name):
            raise forms.ValidationError("Enter a watchlist name without control characters.")
        return name


class InstrumentForm(forms.Form):
    security_id = forms.CharField(
        label="Provider instrument ID",
        max_length=100,
        strip=True,
        help_text=(
            "Use the stable Intrinio ID shown on the instrument details page, "
            "rather than its ticker."
        ),
    )

    def clean_security_id(self):
        identifier = self.cleaned_data["security_id"]
        if not valid_provider_id(identifier):
            raise forms.ValidationError("Enter a valid provider instrument ID.")
        return identifier


class ChooseWatchlistForm(InstrumentForm):
    watchlist = forms.ModelChoiceField(
        queryset=None, label="Watchlist", empty_label="Choose a watchlist"
    )

    def __init__(self, *args, watchlists, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["watchlist"].queryset = watchlists
        self.fields["watchlist"].label_from_instance = lambda watchlist: watchlist.name


class WatchlistPreferencesForm(forms.Form):
    price_basis = forms.ChoiceField(label="Default price basis", choices=tuple(PRICE_BASES.items()))
    volume_basis = forms.ChoiceField(
        label="Default volume basis", choices=tuple(VOLUME_BASES.items())
    )
    instrument_order = forms.ChoiceField(
        label="Instrument order", choices=tuple(INSTRUMENT_ORDERS.items())
    )


class SelectedItemsField(forms.ModelMultipleChoiceField):
    def clean(self, value):
        if isinstance(value, (list, tuple)) and (
            len(value) > MAX_MARKET_ITEMS or len(set(value)) != len(value)
        ):
            raise forms.ValidationError("Choose at most five different instruments per load.")
        return super().clean(value)


class WatchlistMarketForm(forms.Form):
    market_date = forms.DateField(
        label="Daily observation date",
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="An exact date; no earlier trading day is substituted.",
    )
    price_basis = forms.ChoiceField(label="Price basis", choices=tuple(PRICE_BASES.items()))
    volume_basis = forms.ChoiceField(label="Volume basis", choices=tuple(VOLUME_BASES.items()))
    items = SelectedItemsField(
        queryset=None,
        label="Instruments to load",
        widget=forms.CheckboxSelectMultiple,
        help_text="Choose one to five instruments. Each uses at most one data request.",
    )

    def __init__(self, *args, items, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["items"].queryset = items
        self.fields["items"].label_from_instance = lambda item: (
            f"{item.ticker or item.security_id} · {item.name or 'Name unavailable'} · "
            f"{item.exchange_mic or 'MIC unavailable'} · {item.currency or 'Currency unavailable'}"
            f" · {item.security_id}"
        )

    def clean_market_date(self):
        value = self.cleaned_data["market_date"]
        try:
            validate_price_range(value, value)
        except ValueError as error:
            raise forms.ValidationError(str(error)) from None
        return value
