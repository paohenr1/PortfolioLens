"""Private pages never query another owner's portfolios."""

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods

from portfolios import services
from portfolios.forms import PortfolioForm


def unavailable(request):
    return render(request, "portfolios/unavailable.html", status=503)


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
    return render(request, "portfolios/detail.html", {"portfolio": portfolio})
