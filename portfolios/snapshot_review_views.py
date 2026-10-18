"""Private on-demand snapshot diagnostics, with fixed saved date and no result storage."""

from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from portfolios import snapshot_review_services as services
from portfolios.services import PortfolioStorageUnavailable
from portfolios.snapshot_previews import CONFIRMATION
from portfolios.snapshot_services import private_snapshot
from portfolios.views import unavailable


class ReviewLoadForm(forms.Form):
    action = forms.ChoiceField(
        choices=(("load", "Load snapshot review"),),
        initial="load",
        widget=forms.HiddenInput,
    )


@never_cache
@login_required
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def snapshot_review(request, snapshot_id):
    try:
        snapshot = private_snapshot(request.user, snapshot_id)
    except PortfolioStorageUnavailable:
        return unavailable(request)
    form = ReviewLoadForm(request.POST if request.method == "POST" else None)
    result, provider_error, status = None, None, 200
    if request.method == "POST":
        if form.is_valid():
            try:
                inputs, result, provider_error = services.load_review(
                    request.user,
                    snapshot_id,
                    request.META.get("REMOTE_ADDR", "unknown"),
                )
                snapshot = inputs.snapshot
            except ValidationError as error:
                form.add_error(None, error.messages)
                status = 503
            if provider_error:
                status = 429 if provider_error.status == 429 else 503
        else:
            status = 400
    response = render(
        request,
        "portfolios/snapshot_review.html",
        {
            "snapshot": snapshot,
            "form": form,
            "review": result,
            "provider_error": provider_error,
            "confirmation": CONFIRMATION,
        },
        status=status,
    )
    if provider_error and provider_error.retry_after:
        response.headers["Retry-After"] = str(provider_error.retry_after)
    return response
