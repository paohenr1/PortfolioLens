"""Private, explicitly submitted performance calculations; no scheduled requests."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from ledger.domain import LedgerRuleError
from ledger.performance import PerformanceRuleError
from ledger.performance_forms import PerformanceForm
from ledger.performance_services import load_performance
from ledger.services import PortfolioUnavailable, private_portfolio
from ledger.views import private_error
from portfolios.services import PortfolioStorageUnavailable


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def performance(request, portfolio_id):
    try:
        portfolio = private_portfolio(request.user, portfolio_id)
    except (PortfolioStorageUnavailable, PortfolioUnavailable) as error:
        return private_error(request, error)
    form = PerformanceForm(request.POST if request.method == "POST" else None)
    context = {"portfolio": portfolio, "form": form}
    status, provider_error = 200, None
    if request.method == "POST":
        if not form.is_valid():
            status = 400
        else:
            try:
                _, result, valuations, provider_error = load_performance(
                    request.user,
                    portfolio_id,
                    form.cleaned_data["start_date"],
                    form.cleaned_data["end_date"],
                    request.META.get("REMOTE_ADDR", "unknown"),
                )
            except (PortfolioStorageUnavailable, PortfolioUnavailable) as error:
                return private_error(request, error)
            except LedgerRuleError:
                return render(request, "ledger/calculations_unavailable.html", status=503)
            except PerformanceRuleError as error:
                form.add_error(None, str(error))
                status = 400
            else:
                context.update(
                    performance=result, valuations=valuations, provider_error=provider_error
                )
                if provider_error:
                    status = 429 if provider_error.status == 429 else 503
    response = render(request, "ledger/performance.html", context, status=status)
    if provider_error and provider_error.retry_after:
        response.headers["Retry-After"] = str(provider_error.retry_after)
    return response
