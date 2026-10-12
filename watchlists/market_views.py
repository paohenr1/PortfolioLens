"""Private market reads and CSRF-protected saved per-watchlist preferences."""

from datetime import UTC, datetime, timedelta

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods

from watchlists import services
from watchlists.forms import WatchlistMarketForm, WatchlistPreferencesForm
from watchlists.market import PRICE_BASES, VOLUME_BASES
from watchlists.market_services import load_market_information
from watchlists.views import private_error, validation_errors


@never_cache
@login_required
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def preferences(request, watchlist_id):
    try:
        watchlist = services.private_watchlist(request.user, watchlist_id)
    except (services.WatchlistStorageUnavailable, services.WatchlistUnavailable) as error:
        return private_error(request, error)
    form = WatchlistPreferencesForm(
        request.POST if request.method == "POST" else None,
        initial={
            field: getattr(watchlist, field)
            for field in ("price_basis", "volume_basis", "instrument_order")
        },
    )
    if request.method == "POST" and form.is_valid():
        try:
            services.save_preferences(
                user=request.user, watchlist_id=watchlist_id, **form.cleaned_data
            )
        except (services.WatchlistStorageUnavailable, services.WatchlistUnavailable) as error:
            return private_error(request, error)
        except ValidationError as error:
            validation_errors(form, error)
        else:
            return redirect("watchlist_detail", watchlist_id=watchlist_id)
    return render(
        request,
        "watchlists/preferences.html",
        {"watchlist": watchlist, "form": form},
        status=400 if request.method == "POST" else 200,
    )


@never_cache
@login_required
@require_GET
def market_information(request, watchlist_id):
    try:
        watchlist = services.private_watchlist(request.user, watchlist_id)
    except (services.WatchlistStorageUnavailable, services.WatchlistUnavailable) as error:
        return private_error(request, error)
    submitted = any(
        field in request.GET for field in ("market_date", "price_basis", "volume_basis", "items")
    )
    form = WatchlistMarketForm(
        request.GET if submitted else None,
        items=services.ordered_items(watchlist),
        initial={
            "market_date": datetime.now(UTC).date() - timedelta(days=1),
            "price_basis": watchlist.price_basis,
            "volume_basis": watchlist.volume_basis,
        },
    )
    context = {"watchlist": watchlist, "form": form}
    status, rate_limit = 200, None
    if form.is_bound:
        if not form.is_valid():
            status = 400
        else:
            values = form.cleaned_data
            try:
                rows, rate_limit = load_market_information(
                    user=request.user,
                    watchlist_id=watchlist_id,
                    item_ids=tuple(item.pk for item in values["items"]),
                    market_date=values["market_date"],
                    price_basis=values["price_basis"],
                    volume_basis=values["volume_basis"],
                    client_address=request.META.get("REMOTE_ADDR", "unknown"),
                )
                context.update(
                    rows=rows,
                    market_date=values["market_date"],
                    price_label=PRICE_BASES[values["price_basis"]],
                    volume_label=VOLUME_BASES[values["volume_basis"]],
                    rate_limit=rate_limit,
                )
                if rate_limit is not None:
                    status = 429
            except (services.WatchlistStorageUnavailable, services.WatchlistUnavailable) as error:
                return private_error(request, error)
            except ValidationError as error:
                form.add_error(None, error.messages)
                status = 400
    response = render(request, "watchlists/market.html", context, status=status)
    if rate_limit is not None:
        response.headers["Retry-After"] = str(rate_limit.retry_after)
    return response
