"""Private pages never query another owner's portfolios."""

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from ledger.analysis_context import analysis_form, remember_dates, saved_dates
from ledger.domain import LedgerRuleError
from ledger.performance_forms import PerformanceForm
from ledger.services import PortfolioUnavailable
from portfolios import services
from portfolios.automatic_valuation import automatic_valuation
from portfolios.forms import PortfolioForm
from portfolios.overview import overview_context


def unavailable(request):
    return render(request, "portfolios/unavailable.html", status=503)


@never_cache
@login_required
@require_GET
def portfolio_home(request):
    """Skip the picker only when this owner has exactly one portfolio."""
    try:
        identifiers = list(services.owned_portfolios(request.user).values_list("pk", flat=True)[:2])
    except services.PortfolioStorageUnavailable:
        return unavailable(request)
    if len(identifiers) == 1:
        return redirect("portfolio_detail", portfolio_id=identifiers[0])
    return redirect("portfolio_list")


@never_cache
@login_required
@require_GET
def portfolio_list(request):
    try:
        queryset = services.owned_portfolios(request.user)
    except services.PortfolioStorageUnavailable:
        return unavailable(request)
    page = Paginator(queryset, 20).get_page(request.GET.get("page"))
    return render(request, "portfolios/list.html", {"page": page})


@never_cache
@login_required
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def portfolio_create(request):
    try:
        services.require_portfolio_storage()
    except services.PortfolioStorageUnavailable:
        return unavailable(request)
    form = PortfolioForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            portfolio = services.create_portfolio(
                owner=request.user, name=form.cleaned_data["name"]
            )
        except ValidationError as error:
            for field, errors in error.message_dict.items():
                form.add_error(None if field == "__all__" else field, errors)
        else:
            return redirect("portfolio_detail", portfolio_id=portfolio.pk)
    return render(request, "portfolios/create.html", {"form": form})


@never_cache
@login_required
@require_GET
def portfolio_detail(request, portfolio_id):
    try:
        queryset = services.owned_portfolios(request.user)
    except services.PortfolioStorageUnavailable:
        return unavailable(request)
    portfolio = queryset.filter(pk=portfolio_id).first()
    if portfolio is None:
        return render(request, "portfolios/not_found.html", status=404)
    context = {"portfolio": portfolio}
    try:
        context, _ = overview_context(request.user, portfolio_id)
    except LedgerRuleError:
        # Keep correction tools reachable when journal calculations cannot run.
        context["summary_unavailable"] = True
    except services.PortfolioStorageUnavailable:
        return unavailable(request)
    except PortfolioUnavailable:
        return render(request, "portfolios/not_found.html", status=404)
    context["overview_form"] = analysis_form(request, portfolio_id, PerformanceForm)
    context["load_automatic_valuation"] = not context.get("summary_unavailable", False)
    return render(request, "portfolios/detail.html", context)


@never_cache
@login_required
@require_POST
def portfolio_automatic_valuation(request, portfolio_id):
    try:
        result = automatic_valuation(
            request.user,
            portfolio_id,
            request.META.get("REMOTE_ADDR", "unknown"),
            saved_dates(request, portfolio_id),
        )
    except PortfolioUnavailable:
        return render(request, "portfolios/not_found.html", status=404)
    except services.PortfolioStorageUnavailable:
        return unavailable(request)
    except LedgerRuleError as error:
        return render(
            request, "portfolios/automatic_valuation.html", {"issue": str(error)}, status=400
        )
    provider_error = result.provider_error
    status = (429 if provider_error.status == 429 else 503) if provider_error else 200
    response = render(
        request,
        "portfolios/automatic_valuation.html",
        {
            "valuation": result.valuation,
            "performance": result.performance,
            "period": result.period,
            "performance_issue": result.performance_issue,
            "performance_portfolio_id": portfolio_id,
            "issue": result.valuation_issue or (provider_error.message if provider_error else ""),
            "manual_portfolio_id": portfolio_id if result.valuation_issue else None,
            "busy": result.busy,
        },
        status=status,
    )
    if provider_error and provider_error.retry_after:
        response.headers["Retry-After"] = str(provider_error.retry_after)
    return response


@never_cache
@login_required
@require_POST
def portfolio_performance_preference(request, portfolio_id):
    action = request.POST.get("automatic_performance")
    if action not in {"enable", "disable"}:
        return HttpResponseBadRequest("Choose whether to enable automatic performance.")
    try:
        updated = (
            services.owned_portfolios(request.user)
            .filter(pk=portfolio_id)
            .update(automatic_performance_enabled=action == "enable")
        )
    except services.PortfolioStorageUnavailable:
        return unavailable(request)
    if not updated:
        return render(request, "portfolios/not_found.html", status=404)
    return redirect("portfolio_detail", portfolio_id=portfolio_id)


@never_cache
@login_required
@require_POST
def portfolio_overview_load(request, portfolio_id):
    # Resolve ownership before validating dates or requesting any market data.
    from ledger.services import private_portfolio

    try:
        portfolio = private_portfolio(request.user, portfolio_id)
    except services.PortfolioStorageUnavailable:
        return unavailable(request)
    except PortfolioUnavailable:
        return render(request, "portfolios/not_found.html", status=404)
    form = analysis_form(request, portfolio_id, PerformanceForm)
    if portfolio.automatic_performance_enabled:
        form.fields.pop("timing_checked")
    status, provider_error = 200, None
    try:
        dates = None
        if form.is_valid():
            remember_dates(request, portfolio_id, form)
            dates = (form.cleaned_data["start_date"], form.cleaned_data["end_date"])
        else:
            status = 400
        context, provider_error = overview_context(
            request.user,
            portfolio_id,
            dates=dates,
            client_address=request.META.get("REMOTE_ADDR", "unknown"),
        )
    except services.PortfolioStorageUnavailable:
        return unavailable(request)
    except PortfolioUnavailable:
        return render(request, "portfolios/not_found.html", status=404)
    except LedgerRuleError:
        context = {"portfolio": portfolio, "summary_unavailable": True}
        status = 503
    if context.get("valuation_issue"):
        status = 400
    if provider_error:
        status = 429 if provider_error.status == 429 else 503
    context.update(overview_form=form, provider_error=provider_error)
    response = render(request, "portfolios/detail.html", context, status=status)
    if provider_error and provider_error.retry_after:
        response.headers["Retry-After"] = str(provider_error.retry_after)
    return response
