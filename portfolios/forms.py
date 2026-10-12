from django import forms


class PortfolioForm(forms.Form):
    name = forms.CharField(max_length=100, label="Portfolio name", strip=True)
    # A required choice keeps USD explicit without implying FX support.
    reporting_currency = forms.ChoiceField(
        choices=(("USD", "USD — U.S. dollar"),), label="Reporting currency"
    )

    def clean_name(self):
        value = self.cleaned_data["name"]
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise forms.ValidationError("Enter a portfolio name without control characters.")
        return value
