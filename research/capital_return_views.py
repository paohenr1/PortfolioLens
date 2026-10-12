import logging
from datetime import UTC, datetime

from django.http import Http404
from django.shortcuts import render
from django.views.decorators.http import require_GET

from market_data.errors import ProviderError
from market_data.intrinio import valid_security_id
from research import services
from research.capital_return_forms import CapitalReturnForm
from research.capital_returns import calculate_capital_returns
from research.fundamentals import metadata_time
from research.views import _error_page

logger = logging.getLogger("research")


@require_GET
def capital_returns(request, security_id):
    if not valid_security_id(security_id):
        raise Http404("Invalid instrument identifier.")
    form = CapitalReturnForm(
        request.GET
        if any(field in request.GET for field in ("fiscal_year", "fiscal_period"))
        else None,
        initial={"fiscal_year": datetime.now(UTC).year - 1},
    )
    context = {"form": form, "security_id": security_id}
    status = 200
    if form.is_bound:
        if not form.is_valid():
            status = 400
        else:
            try:
                bundle = services.annual_profitability(
                    security_id,
                    form.cleaned_data["fiscal_year"],
                    request.META.get("REMOTE_ADDR", ""),
                )
                result = calculate_capital_returns(bundle)
                sources = tuple(
                    {
                        "label": label,
                        "statement": source,
                        "filing_time": metadata_time(source.fundamental.filing_date),
                        "updated_time": metadata_time(source.fundamental.updated_date),
                        "calculable_time": metadata_time(source.fundamental.first_calculable),
                    }
                    for label, source in (
                        ("Income statement", bundle.income),
                        ("Opening balance sheet", bundle.opening_balance),
                        ("Closing balance sheet", bundle.closing_balance),
                    )
                )
                context.update(bundle=bundle, capital_result=result, sources=sources)
            except ProviderError as error:
                return _error_page(request, "research/capital_returns.html", context, error)
            except Exception:
                logger.exception("Unexpected return-on-balance failure")
                return _error_page(
                    request, "research/capital_returns.html", context, ProviderError()
                )
    response = render(request, "research/capital_returns.html", context, status=status)
    response.headers["Cache-Control"] = "no-store"
    return response
