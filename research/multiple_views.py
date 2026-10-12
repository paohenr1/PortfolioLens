import logging
from datetime import UTC, datetime, timedelta

from django.http import Http404
from django.shortcuts import render
from django.views.decorators.http import require_GET

from market_data.errors import ProviderError
from market_data.intrinio import valid_security_id
from research import services
from research.fundamentals import metadata_time
from research.multiple_forms import AnnualMultipleForm
from research.multiples import calculate_annual_multiples
from research.views import _error_page

logger = logging.getLogger("research")


@require_GET
def annual_multiples(request, security_id):
    if not valid_security_id(security_id):
        raise Http404("Invalid instrument identifier.")
    fields = ("fiscal_year", "price_date", "basis_confirmed", "fiscal_period")
    submitted = any(field in request.GET for field in fields)
    now = datetime.now(UTC)
    form = AnnualMultipleForm(
        request.GET if submitted else None,
        initial={"fiscal_year": now.year - 1, "price_date": now.date() - timedelta(days=1)},
    )
    context = {"form": form, "security_id": security_id}
    status = 200
    if form.is_bound:
        if not form.is_valid():
            status = 400
        else:
            try:
                bundle = services.annual_valuation(
                    security_id,
                    form.cleaned_data["fiscal_year"],
                    form.cleaned_data["price_date"],
                    request.META.get("REMOTE_ADDR", ""),
                )
                result = calculate_annual_multiples(
                    bundle,
                    form.cleaned_data["price_date"],
                    basis_confirmed=form.cleaned_data["basis_confirmed"],
                )
                period = bundle.income.fundamental
                context.update(
                    bundle=bundle,
                    multiples=result,
                    filing_time=metadata_time(period.filing_date),
                    updated_time=metadata_time(period.updated_date),
                    calculable_time=metadata_time(period.first_calculable),
                )
            except ProviderError as error:
                return _error_page(request, "research/multiples.html", context, error)
            except Exception:
                logger.exception("Unexpected annual-multiples failure")
                return _error_page(request, "research/multiples.html", context, ProviderError())
    response = render(request, "research/multiples.html", context, status=status)
    response.headers["Cache-Control"] = "no-store"
    return response
