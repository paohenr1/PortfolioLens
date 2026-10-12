import logging
from datetime import UTC, datetime

from django.http import Http404
from django.shortcuts import render
from django.views.decorators.http import require_GET

from market_data.errors import ProviderError
from market_data.fundamentals import STATEMENTS
from market_data.intrinio import valid_security_id
from research import services
from research.fundamentals import metadata_time
from research.trend_forms import StatementTrendForm
from research.trends import calculate_statement_trends, trend_chart
from research.views import _error_page

logger = logging.getLogger("research")


@require_GET
def statement_trends(request, security_id):
    if not valid_security_id(security_id):
        raise Http404("Invalid instrument identifier.")
    submitted = any(
        field in request.GET for field in ("statement", "end_year", "years", "fiscal_period")
    )
    form = StatementTrendForm(
        request.GET if submitted else None,
        initial={
            "statement": "income_statement",
            "end_year": datetime.now(UTC).year - 1,
            "years": 3,
        },
    )
    context = {"form": form, "security_id": security_id}
    status = 200
    if form.is_bound:
        if not form.is_valid():
            status = 400
        else:
            try:
                bundle = services.annual_statement_series(
                    security_id,
                    form.cleaned_data["statement"],
                    form.cleaned_data["end_year"],
                    form.cleaned_data["years"],
                    request.META.get("REMOTE_ADDR", ""),
                )
                result = calculate_statement_trends(bundle)
                sources = tuple(
                    {
                        "statement": source,
                        "filing_time": metadata_time(source.fundamental.filing_date),
                        "updated_time": metadata_time(source.fundamental.updated_date),
                        "calculable_time": metadata_time(source.fundamental.first_calculable),
                    }
                    for source in bundle.statements
                )
                panels = tuple(
                    {"metric": metric, "chart": trend_chart(metric)} for metric in result.metrics
                )
                context.update(
                    bundle=bundle,
                    trends=result,
                    panels=panels,
                    sources=sources,
                    statement_label=STATEMENTS[form.cleaned_data["statement"]],
                    is_balance=form.cleaned_data["statement"] == "balance_sheet_statement",
                )
            except ProviderError as error:
                return _error_page(request, "research/trends.html", context, error)
            except Exception:
                logger.exception("Unexpected statement-trend failure")
                return _error_page(request, "research/trends.html", context, ProviderError())
    response = render(request, "research/trends.html", context, status=status)
    response.headers["Cache-Control"] = "no-store"
    return response
