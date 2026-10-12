"""Session authentication and a current-user-only account boundary."""

from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import (
    LoginView,
    LogoutView,
    PasswordChangeDoneView,
    PasswordChangeView,
)
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET
from django.views.generic import CreateView

from accounts.forms import RegistrationForm
from accounts.limits import reserve_attempt
from operations.rate_limits import BudgetUnavailable


@method_decorator(never_cache, name="dispatch")
class PrivateResponseMixin:
    """Prevent account forms and identity from being stored in shared caches."""

    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)


class AttemptLimitMixin:
    def dispatch(self, request, *args, **kwargs):
        if request.method == "POST":
            # Forwarded headers are untrusted until a deployment proxy is verified.
            try:
                retry_after = reserve_attempt(request.META.get("REMOTE_ADDR", "unknown"))
            except BudgetUnavailable:
                return render(request, "accounts/unavailable.html", status=503)
            if retry_after is not None:
                response = render(request, "accounts/rate_limited.html", status=429)
                response.headers["Retry-After"] = str(retry_after)
                return response
        return super().dispatch(request, *args, **kwargs)


@method_decorator(sensitive_post_parameters(), name="dispatch")
class SignInView(PrivateResponseMixin, AttemptLimitMixin, LoginView):
    template_name = "accounts/sign_in.html"
    # Django validates next against this request's host and HTTPS requirements.
    http_method_names = ["get", "post", "head", "options"]


class SignOutView(PrivateResponseMixin, LogoutView):
    next_page = reverse_lazy("home")
    # A caller cannot replace the sign-out destination with a query/POST field.
    redirect_field_name = None


@method_decorator(sensitive_post_parameters(), name="dispatch")
@method_decorator(never_cache, name="dispatch")
class RegisterView(PrivateResponseMixin, AttemptLimitMixin, CreateView):
    form_class = RegistrationForm
    template_name = "accounts/register.html"
    http_method_names = ["get", "post", "head", "options"]

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("account")
        if not settings.ALLOW_REGISTRATION:
            raise Http404("Not found.")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.save()
        # Django rotates the anonymous session key at login; passwords are hashed.
        login(self.request, user)
        return redirect("account")


@method_decorator(sensitive_post_parameters(), name="dispatch")
class ChangePasswordView(PrivateResponseMixin, AttemptLimitMixin, PasswordChangeView):
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("password_change_done")
    http_method_names = ["get", "post", "head", "options"]


class ChangePasswordDoneView(PrivateResponseMixin, PasswordChangeDoneView):
    template_name = "accounts/password_change_done.html"
    http_method_names = ["get", "head", "options"]


@never_cache
@login_required
@require_GET
def account(request):
    # Never accept a user ID from the URL or form. Future private objects need
    # owner-filtered queries and their own isolation tests, not merely this login gate.
    return render(request, "accounts/account.html", {"account_user": request.user})
