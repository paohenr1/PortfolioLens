"""Explicit-date company market capitalization; blank forms perform no I/O."""

import logging
from datetime import UTC, datetime, timedelta

from django import forms
from django.http import Http404
from django.shortcuts import render
from django.views.decorators.http import require_GET

from market_data.errors import ProviderError
from market_data.intrinio import valid_security_id
from market_data.prices import validate_price_range
from research import services
from research.fundamentals import financial_text
from research.views import _error_page

logger = logging.getLogger("research")


class MarketCapitalizationForm(forms.Form):
    valuation_date = forms.DateField(
        label="Market capitalization date",
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="An exact provider observation date; no earlier date is substituted.",
    )

    def clean_valuation_date(self):
        value = self.cleaned_data["valuation_date"]
        try:
            validate_price_range(value, value)
        except ValueError as error:
            raise forms.ValidationError(str(error)) from None
        return value


@require_GET
def market_capitalization(request, security_id):
    if not valid_security_id(security_id):
        raise Http404("Invalid instrument identifier.")
    form = MarketCapitalizationForm(
        request.GET if "valuation_date" in request.GET else None,
        initial={"valuation_date": datetime.now(UTC).date() - timedelta(days=1)},
    )
    context = {"form": form, "security_id": security_id}
    status = 200
    if form.is_bound:
        if not form.is_valid():
            status = 400
        else:
            try:
                source = services.market_capitalization(
                    security_id,
                    form.cleaned_data["valuation_date"],
                    request.META.get("REMOTE_ADDR", ""),
                )
                issue = None
                if not source.pagination_complete:
                    issue = "The provider response is incomplete; no additional page was requested."
                elif not source.observation_present:
                    issue = "No market capitalization observation was supplied for this exact date."
                elif source.value is None:
                    issue = "The provider supplied this date with no market capitalization value."
                context.update(
                    capitalization=source,
                    value_text=financial_text(source.value) if issue is None else "Unavailable",
                    availability_issue=issue,
                )
            except ProviderError as error:
                return _error_page(request, "research/capitalization.html", context, error)
            except Exception:
                logger.exception("Unexpected market-capitalization failure")
                return _error_page(
                    request, "research/capitalization.html", context, ProviderError()
                )
    response = render(request, "research/capitalization.html", context, status=status)
    response.headers["Cache-Control"] = "no-store"
    return response
