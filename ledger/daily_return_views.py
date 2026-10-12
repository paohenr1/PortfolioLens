"""Explicit private session-return action with the existing ownership/CSRF guards."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from ledger.benchmark_chart import comparison_chart
from ledger.daily_return_forms import DailyReturnForm
from ledger.daily_return_services import load_daily_comparison
from ledger.domain import LedgerRuleError
from ledger.performance import PerformanceRuleError
from ledger.risk import calculate_daily_risk
from ledger.risk_chart import drawdown_chart
from ledger.services import PortfolioUnavailable, private_portfolio
from ledger.sharpe import calculate_sharpe
from ledger.views import private_error
from portfolios.services import PortfolioStorageUnavailable


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def daily_returns(request, portfolio_id):
    try:
        portfolio = private_portfolio(request.user, portfolio_id)
    except (PortfolioStorageUnavailable, PortfolioUnavailable) as error:
        return private_error(request, error)
    form = DailyReturnForm(request.POST if request.method == "POST" else None)
    context = {"portfolio": portfolio, "form": form}
    status, provider_error = 200, None
    if request.method == "POST":
        if not form.is_valid():
            status = 400
        else:
            try:
                _, result, valuations, provider_error, comparison = load_daily_comparison(
                    request.user,
                    portfolio_id,
                    form.cleaned_data["start_date"],
                    form.cleaned_data["end_date"],
                    request.META.get("REMOTE_ADDR", "unknown"),
                    form.cleaned_data["benchmark_id"],
                )
            except (PortfolioStorageUnavailable, PortfolioUnavailable) as error:
                return private_error(request, error)
            except LedgerRuleError:
                return render(request, "ledger/calculations_unavailable.html", status=503)
            except PerformanceRuleError as error:
                form.add_error(None, str(error))
                status = 400
            else:
                risk = calculate_daily_risk(result)
                context.update(
                    performance=result,
                    valuations=valuations,
                    provider_error=provider_error,
                    risk=risk,
                    drawdown_chart=drawdown_chart(risk),
                    comparison=comparison,
                    comparison_chart=comparison_chart(comparison),
                    sharpe=(
                        calculate_sharpe(result, form.cleaned_data["annual_risk_free_percent"])
                        if form.cleaned_data["annual_risk_free_percent"] is not None
                        else None
                    ),
                )
                if provider_error:
                    status = 429 if provider_error.status == 429 else 503
    response = render(request, "ledger/daily_returns.html", context, status=status)
    if provider_error and provider_error.retry_after:
        response.headers["Retry-After"] = str(provider_error.retry_after)
    return response
