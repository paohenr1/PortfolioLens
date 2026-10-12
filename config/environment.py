"""Validate startup configuration without exposing values in error messages."""

import ipaddress
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field

from django.core.exceptions import ImproperlyConfigured

_HOSTNAME = re.compile(
    r"(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)*"
    r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
)


@dataclass(frozen=True)
class Environment:
    name: str
    debug: bool
    allowed_hosts: tuple[str, ...]
    # repr=False prevents accidental disclosure when configuration is inspected.
    secret_key: str = field(repr=False)
    intrinio_api_key: str = field(repr=False)
    rate_limit_backend: str = "memory"
    trust_proxy_https: bool = False
    private_site: bool = False
    allow_registration: bool = True

    @property
    def production(self) -> bool:
        return self.name == "production"


def _boolean(value: str, name="DJANGO_DEBUG") -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1"}:
        return True
    if normalized in {"false", "0"}:
        return False
    raise ImproperlyConfigured(f"{name} must be true, false, 1, or 0.")


def _valid_host(host: str) -> bool:
    if host.startswith("[") and host.endswith("]"):
        try:
            ipaddress.IPv6Address(host[1:-1])
        except ValueError:
            return False
        return True
    return len(host) <= 253 and _HOSTNAME.fullmatch(host) is not None


def load_environment(environ: Mapping[str, str]) -> Environment:
    """Fail closed for invalid production settings; never include supplied values."""
    name = environ.get("DJANGO_ENV", "development").strip().lower()
    if name not in {"development", "production"}:
        raise ImproperlyConfigured("DJANGO_ENV must be development or production.")

    production = name == "production"
    debug = _boolean(environ.get("DJANGO_DEBUG", "false" if production else "true"))
    if production and debug:
        raise ImproperlyConfigured("DJANGO_DEBUG must be false in production.")

    secret_key = environ.get("DJANGO_SECRET_KEY", "").strip()
    if production and (
        len(secret_key) < 50
        or len(set(secret_key)) < 5
        or secret_key.startswith("django-insecure-")
    ):
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be a strong production secret.")
    if not secret_key:
        # A per-process development key avoids committing any reusable secret.
        # Set a local key if sessions must survive development server restarts.
        secret_key = secrets.token_urlsafe(64)

    default_hosts = "" if production else "localhost,127.0.0.1,[::1]"
    raw_hosts = environ.get("DJANGO_ALLOWED_HOSTS", default_hosts)
    allowed_hosts = tuple(host.strip().lower() for host in raw_hosts.split(",") if host.strip())
    if not allowed_hosts or any(not _valid_host(host) for host in allowed_hosts):
        raise ImproperlyConfigured(
            "DJANGO_ALLOWED_HOSTS must list explicit hostnames or IP addresses without ports."
        )

    backend = environ.get("DJANGO_RATE_LIMIT_BACKEND", "postgresql" if production else "memory")
    if backend not in {"memory", "postgresql"} or (production and backend != "postgresql"):
        raise ImproperlyConfigured(
            "DJANGO_RATE_LIMIT_BACKEND must be memory or postgresql; "
            "production requires postgresql."
        )
    trust_proxy = _boolean(
        environ.get("DJANGO_TRUST_PROXY_HTTPS", "false"), "DJANGO_TRUST_PROXY_HTTPS"
    )
    if trust_proxy and not production:
        raise ImproperlyConfigured("DJANGO_TRUST_PROXY_HTTPS requires production mode.")
    private_site = _boolean(
        environ.get("DJANGO_PRIVATE_SITE", "true" if production else "false"),
        "DJANGO_PRIVATE_SITE",
    )
    allow_registration = _boolean(
        environ.get("DJANGO_ALLOW_REGISTRATION", "false" if production else "true"),
        "DJANGO_ALLOW_REGISTRATION",
    )

    return Environment(
        name=name,
        debug=debug,
        allowed_hosts=allowed_hosts,
        secret_key=secret_key,
        intrinio_api_key=environ.get("INTRINIO_API_KEY", "").strip(),
        rate_limit_backend=backend,
        trust_proxy_https=trust_proxy,
        private_site=private_site,
        allow_registration=allow_registration,
    )
