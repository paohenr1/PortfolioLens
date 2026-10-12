"""GET displays private forms; only CSRF-protected POST can mutate bookmarks."""

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods

from market_data.errors import ProviderError
from watchlists import services
from watchlists.forms import ChooseWatchlistForm, InstrumentForm, WatchlistForm


def private_error(request, error):
    unavailable = isinstance(error, services.WatchlistStorageUnavailable)
    return render(
        request,
        "watchlists/error.html",
        {"storage_unavailable": unavailable},
        status=503 if unavailable else 404,
    )


def validation_errors(form, error):
    if hasattr(error, "message_dict"):
        for field, messages in error.message_dict.items():
            form.add_error(None if field == "__all__" else field, messages)
    else:
        form.add_error(None, error.messages)


@never_cache
@login_required
@require_GET
def watchlist_list(request):
    try:
        queryset = services.owned_watchlists(request.user)
    except services.WatchlistStorageUnavailable as error:
        return private_error(request, error)
    return render(
        request,
        "watchlists/list.html",
        {
            "page": Paginator(queryset, 20).get_page(request.GET.get("page")),
        },
    )


@never_cache
@login_required
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def watchlist_create(request):
    try:
        services.owned_watchlists(request.user)
    except services.WatchlistStorageUnavailable as error:
        return private_error(request, error)
    form = WatchlistForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            watchlist = services.create_watchlist(user=request.user, name=form.cleaned_data["name"])
        except ValidationError as error:
            validation_errors(form, error)
        else:
            return redirect("watchlist_detail", watchlist_id=watchlist.pk)
    return render(
        request,
        "watchlists/create.html",
        {"form": form},
        status=400 if request.method == "POST" else 200,
    )


@never_cache
@login_required
@require_GET
def watchlist_detail(request, watchlist_id):
    try:
        watchlist = services.private_watchlist(request.user, watchlist_id)
    except (services.WatchlistStorageUnavailable, services.WatchlistUnavailable) as error:
        return private_error(request, error)
    return render(
        request,
        "watchlists/detail.html",
        {
            "watchlist": watchlist,
            "page": Paginator(services.ordered_items(watchlist), 25).get_page(
                request.GET.get("page")
            ),
        },
    )


@never_cache
@login_required
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def instrument_add(request, watchlist_id=None):
    try:
        queryset = services.owned_watchlists(request.user)
        watchlist = services.private_watchlist(request.user, watchlist_id) if watchlist_id else None
    except (services.WatchlistStorageUnavailable, services.WatchlistUnavailable) as error:
        return private_error(request, error)
    arguments = {"initial": {"security_id": request.GET.get("security_id", "")[:100]}}
    if watchlist:
        form = InstrumentForm(request.POST if request.method == "POST" else None, **arguments)
    else:
        form = ChooseWatchlistForm(
            request.POST if request.method == "POST" else None,
            watchlists=queryset,
            **arguments,
        )
    status, provider_error = 200, None
    if request.method == "POST":
        status = 400
        if form.is_valid():
            target = watchlist or form.cleaned_data["watchlist"]
            try:
                services.add_instrument(
                    user=request.user,
                    watchlist_id=target.pk,
                    security_id=form.cleaned_data["security_id"],
                    client_address=request.META.get("REMOTE_ADDR", "unknown"),
                )
            except (services.WatchlistStorageUnavailable, services.WatchlistUnavailable) as error:
                return private_error(request, error)
            except ValidationError as error:
                validation_errors(form, error)
            except ProviderError as error:
                provider_error, status = error, error.status
            else:
                return redirect("watchlist_detail", watchlist_id=target.pk)
    response = render(
        request,
        "watchlists/add.html",
        {
            "form": form,
            "watchlist": watchlist,
            "provider_error": provider_error,
        },
        status=status,
    )
    if provider_error and provider_error.retry_after:
        response.headers["Retry-After"] = str(provider_error.retry_after)
    return response


@never_cache
@login_required
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def instrument_remove(request, watchlist_id, item_id):
    try:
        watchlist, item = services.private_item(request.user, watchlist_id, item_id)
        if request.method == "POST":
            services.remove_instrument(
                user=request.user, watchlist_id=watchlist_id, item_id=item_id
            )
            return redirect("watchlist_detail", watchlist_id=watchlist_id)
    except (services.WatchlistStorageUnavailable, services.WatchlistUnavailable) as error:
        return private_error(request, error)
    return render(request, "watchlists/remove.html", {"watchlist": watchlist, "item": item})
