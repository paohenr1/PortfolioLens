"""Short-lived signed previews bind the reviewed intent, owner and journal version."""

from dataclasses import asdict

from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods

from ledger import corrections
from ledger.correction_forms import ReplacementForm, SaveCorrectionForm, VoidForm
from ledger.domain import LedgerRuleError
from ledger.models import Correction
from ledger.services import PortfolioUnavailable, private_portfolio
from ledger.views import private_error
from market_data.errors import ProviderError
from portfolios.services import PortfolioStorageUnavailable

PREVIEW_SALT = "ledger.correction.v1"
PREVIEW_MAX_AGE = 900


@never_cache
@login_required
@require_GET
def audit(request, portfolio_id):
    try:
        portfolio = private_portfolio(request.user, portfolio_id)
    except (PortfolioStorageUnavailable, PortfolioUnavailable) as error:
        return private_error(request, error)
    queryset = (
        Correction.objects.filter(portfolio=portfolio)
        .select_related("target", "replacement")
        .order_by("-recorded_at", "id")
    )
    return render(
        request,
        "ledger/audit.html",
        {
            "portfolio": portfolio,
            "page": Paginator(queryset, 20).get_page(request.GET.get("page")),
        },
    )


@never_cache
@login_required
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def correct(request, portfolio_id, target_id, void=False):
    try:
        portfolio, target = corrections.private_target(request.user, portfolio_id, target_id)
    except (PortfolioStorageUnavailable, PortfolioUnavailable) as error:
        return private_error(request, error)
    form_class = VoidForm if void else ReplacementForm
    initial = {key: value for key, value in asdict(target.as_input()).items()}
    form = form_class(initial=initial)
    context = {"portfolio": portfolio, "target": target, "void": void, "form": form}
    status, provider_error = 200, None
    if request.method == "POST":
        status = 400
        if request.POST.get("stage") == "save":
            save_form = SaveCorrectionForm(request.POST)
            context["save_form"] = save_form
            save_valid = save_form.is_valid()
            if "preview_token" in save_form.cleaned_data:
                try:
                    payload = signing.loads(
                        save_form.cleaned_data["preview_token"],
                        salt=PREVIEW_SALT,
                        max_age=PREVIEW_MAX_AGE,
                    )
                    if not isinstance(payload, dict) or (
                        payload.get("owner") != str(request.user.pk)
                        or payload.get("portfolio") != str(portfolio.pk)
                        or payload.get("target") != str(target.pk)
                        or payload.get("void") is not void
                        or not isinstance(payload.get("fields"), dict)
                    ):
                        raise signing.BadSignature()
                    form = form_class(payload["fields"])
                    if not form.is_valid():
                        raise signing.BadSignature()
                    context["form"] = form
                    if not save_valid:
                        _, _, before, after, _ = corrections.preview_correction(
                            user=request.user,
                            portfolio_id=portfolio.pk,
                            target_id=target.pk,
                            intent=None if void else form.intent,
                            reason=form.cleaned_data["reason"],
                        )
                        context.update(
                            before=before,
                            after=after,
                            reason=form.cleaned_data["reason"],
                            replacement=None if void else form.intent,
                        )
                        return render(request, "ledger/correct.html", context, status=400)
                    corrections.commit_correction(
                        user=request.user,
                        portfolio_id=portfolio.pk,
                        target_id=target.pk,
                        intent=None if void else form.intent,
                        reason=form.cleaned_data["reason"],
                        client_key=form.cleaned_data["client_key"],
                        expected_version=payload.get("version"),
                        client_address=request.META.get("REMOTE_ADDR", "unknown"),
                    )
                except signing.BadSignature:
                    context["correction_error"] = (
                        "This preview is invalid or expired. Preview the correction again."
                    )
                except LedgerRuleError as error:
                    context["correction_error"] = str(error)
                except (PortfolioStorageUnavailable, PortfolioUnavailable) as error:
                    return private_error(request, error)
                except ProviderError as error:
                    provider_error, status = error, error.status
                else:
                    return redirect("ledger_audit", portfolio_id=portfolio.pk)
        else:
            form = form_class(request.POST)
            context["form"] = form
            if form.is_valid():
                try:
                    _, _, before, after, version = corrections.preview_correction(
                        user=request.user,
                        portfolio_id=portfolio.pk,
                        target_id=target.pk,
                        intent=None if void else form.intent,
                        reason=form.cleaned_data["reason"],
                    )
                except LedgerRuleError as error:
                    form.add_error(None, str(error))
                else:
                    fields = {
                        key: str(value) if value is not None else ""
                        for key, value in form.cleaned_data.items()
                    }
                    token = signing.dumps(
                        {
                            "owner": str(request.user.pk),
                            "portfolio": str(portfolio.pk),
                            "target": str(target.pk),
                            "void": void,
                            "fields": fields,
                            "version": version,
                        },
                        salt=PREVIEW_SALT,
                    )
                    context.update(
                        before=before,
                        after=after,
                        reason=form.cleaned_data["reason"],
                        replacement=None if void else form.intent,
                        save_form=SaveCorrectionForm(initial={"preview_token": token}),
                    )
                    status = 200
    context["provider_error"] = provider_error
    response = render(request, "ledger/correct.html", context, status=status)
    if provider_error and provider_error.retry_after:
        response.headers["Retry-After"] = str(provider_error.retry_after)
    return response
