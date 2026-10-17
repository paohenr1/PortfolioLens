"""Private, transient holdings validation; no model writes or provider requests."""

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from portfolios.holdings_forms import HoldingsPreviewForm


@never_cache
@login_required
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def holdings_preview(request):
    if not request.user.is_active:
        raise PermissionDenied
    data = request.POST if request.method == "POST" else None
    upload_error = request.holdings_upload.error
    form = HoldingsPreviewForm(
        data,
        request.FILES if request.method == "POST" and not upload_error else None,
    )
    preview = None
    status = 200
    if request.method == "POST":
        valid = form.is_valid()
        if upload_error:
            form.add_error("holdings_file", upload_error)
            status = 400
        elif valid:
            preview = form.cleaned_data
    return render(
        request,
        "portfolios/holdings_preview.html",
        {"form": form, "preview": preview, "csv_issues": getattr(form, "csv_issues", ())},
        status=status,
    )
