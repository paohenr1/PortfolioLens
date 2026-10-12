"""Browser restrictions for an interface that needs no external assets."""

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.utils.cache import add_never_cache_headers


class ResponsePolicyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        # Also cover routing, CSRF, and exception responses outside view decorators.
        if (
            (settings.PRIVATE_SITE and not request.path.startswith(settings.STATIC_URL))
            or request.path.startswith(("/portfolios/", "/watchlists/", "/password/"))
            or request.path
            in {
                "/account/",
                "/register/",
                "/sign-in/",
                "/sign-out/",
            }
        ):
            add_never_cache_headers(response)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self'; font-src 'self'; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
        )
        return response


class PrivateSiteMiddleware:
    """Production research requires an active session, including its query routes."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        allowed = {"/sign-in/", "/sign-out/", "/register/", "/health/live/"}
        if (
            settings.PRIVATE_SITE
            and request.path not in allowed
            and not request.path.startswith(settings.STATIC_URL)
            and (not request.user.is_authenticated or not request.user.is_active)
        ):
            return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)
        return self.get_response(request)
