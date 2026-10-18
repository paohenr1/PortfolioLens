"""Private snapshot inputs; all provider calls and mutations require explicit POST."""

from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from market_data.errors import ProviderError
from portfolios import snapshot_previews as previews
from portfolios import snapshot_resolution as resolution
from portfolios import snapshot_services as services
from portfolios.services import PortfolioStorageUnavailable
from portfolios.views import unavailable


class SelectionForm(forms.Form):
    def __init__(self, payload, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for index, row in enumerate(payload["rows"]):
            self.fields[f"holding_{index}"] = forms.ChoiceField(
                label=f"Holding {index + 1}: {row['ticker']} · {row['exchange_mic']}",
                choices=[("", "Choose an instrument")]
                + [
                    (
                        choice["security_id"],
                        f"{choice['security_id']} · {choice['name'] or 'Name unavailable'} · "
                        f"{choice['exchange_mic']} · {choice['currency']}",
                    )
                    for choice in row["choices"]
                ],
            )


class ConfirmationForm(forms.Form):
    confirmed = forms.BooleanField(label=previews.CONFIRMATION)


class DeletionForm(forms.Form):
    confirmed = forms.BooleanField(label="Delete this snapshot and its holdings.")


@never_cache
@login_required
@sensitive_post_parameters()
@require_POST
def snapshot_import(request):
    try:
        services.owned_snapshots(request.user)
    except PortfolioStorageUnavailable:
        return unavailable(request)
    payload, form, token, issues, provider_error, status = None, None, "", [], None, 200
    action = request.POST.get("action")
    try:
        payload = previews.decode(request.POST.get("preview"), request.user)
        if action == "find":
            payload, issues, provider_error = resolution.find_matches(
                payload, request.user, request.META.get("REMOTE_ADDR", "unknown")
            )
        elif action == "verify":
            previews.validate(payload, request.user, stage="matches")
            form = SelectionForm(payload, request.POST)
            if form.is_valid():
                payload = resolution.validate_selections(
                    payload,
                    list(form.cleaned_data.values()),
                    request.user,
                    request.META.get("REMOTE_ADDR", "unknown"),
                )
                form = None
            else:
                status = 400
        elif action == "save":
            previews.validate(payload, request.user, stage="verified")
            form = ConfirmationForm(request.POST)
            if form.is_valid():
                snapshot = services.save_snapshot(
                    user=request.user,
                    token=request.POST.get("preview"),
                    confirmed=form.cleaned_data["confirmed"],
                )
                return redirect("snapshot_detail", snapshot_id=snapshot.pk)
            status = 400
        else:
            raise ValidationError("Choose a supported import action.")
    except ValidationError as error:
        issues.extend(error.messages)
        status = 400
    except ProviderError as error:
        provider_error = error
    if payload is not None:
        try:
            token = previews.encode(payload, request.user)
        except ValidationError:
            payload = None
            issues = [previews.INVALID]
            status = 400
    complete = payload is not None and all(row["choices"] for row in payload["rows"])
    if payload and form is None:
        if payload["stage"] == "verified":
            form = ConfirmationForm()
        elif payload["stage"] == "matches" and complete:
            form = SelectionForm(payload)
    response = render(
        request,
        "portfolios/snapshot_import.html",
        {
            "preview": payload,
            "token": token,
            "form": form,
            "issues": issues,
            "complete": complete,
            "provider_error": provider_error,
        },
        status=provider_error.status if provider_error else status,
    )
    if provider_error and provider_error.retry_after:
        response.headers["Retry-After"] = str(provider_error.retry_after)
    return response


@never_cache
@login_required
@require_GET
def snapshot_list(request):
    try:
        snapshots = services.owned_snapshots(request.user)
    except PortfolioStorageUnavailable:
        return unavailable(request)
    return render(request, "portfolios/snapshot_list.html", {"snapshots": snapshots})


@never_cache
@login_required
@require_GET
def snapshot_detail(request, snapshot_id):
    try:
        snapshot = services.private_snapshot(request.user, snapshot_id)
    except PortfolioStorageUnavailable:
        return unavailable(request)
    return render(
        request,
        "portfolios/snapshot_detail.html",
        {
            "snapshot": snapshot,
            "confirmation": previews.CONFIRMATION,
        },
    )


@never_cache
@login_required
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def snapshot_delete(request, snapshot_id):
    try:
        snapshot = services.private_snapshot(request.user, snapshot_id)
        form = DeletionForm(request.POST if request.method == "POST" else None)
        if request.method == "POST":
            if form.is_valid():
                services.delete_snapshot(user=request.user, snapshot_id=snapshot_id)
                return redirect("snapshot_list")
    except PortfolioStorageUnavailable:
        return unavailable(request)
    return render(
        request,
        "portfolios/snapshot_delete.html",
        {"snapshot": snapshot, "form": form},
        status=400 if request.method == "POST" else 200,
    )
