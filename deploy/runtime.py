"""Small reviewed production-server options; keep deployment policy explicit."""

import json
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from config.database import database_settings
from config.environment import load_environment

ROOT = Path(__file__).resolve().parent.parent


def _integer(environ, name, default, minimum, maximum):
    value = environ.get(name, str(default))
    if (
        len(value) > len(str(maximum))
        or not value.isascii()
        or not value.isdecimal()
        or not minimum <= int(value) <= maximum
    ):
        raise ImproperlyConfigured(f"{name} is outside its supported range.")
    return int(value)


def gunicorn_options(environ):
    current = load_environment(environ)
    if not current.production:
        raise ImproperlyConfigured("Production serving requires DJANGO_ENV=production.")
    database_settings(environ, ROOT, production=True)
    if environ.get("GUNICORN_CMD_ARGS"):
        raise ImproperlyConfigured("Use the reviewed server configuration, not GUNICORN_CMD_ARGS.")
    host = environ.get("STOCK_BIND_HOST", "127.0.0.1")
    if host not in {"127.0.0.1", "0.0.0.0"}:
        raise ImproperlyConfigured("STOCK_BIND_HOST must be an explicit supported bind address.")
    return {
        "chdir": str(ROOT),
        "bind": f"{host}:{_integer(environ, 'PORT', 8000, 1024, 65535)}",
        # Start small; another worker does not grant a new PostgreSQL allowance.
        "workers": _integer(environ, "STOCK_WORKERS", 1, 1, 4),
        "worker_class": "sync",
        "timeout": 180,
        "graceful_timeout": 30,
        "max_requests": 500,
        "max_requests_jitter": 50,
        "preload_app": False,
        "accesslog": None,
        "errorlog": "-",
        "loglevel": "warning",
        # Gunicorn must not implicitly trust scheme headers before Django's
        # explicit ingress policy. Otherwise its default loopback trust bypasses it.
        "forwarded_allow_ips": "",
        "secure_scheme_headers": {},
    }


def check_static_release(root=ROOT):
    static = root / "staticfiles"
    try:
        manifest = json.loads((static / "staticfiles.json").read_text())
        for original in ("research/site.css", "research/prices.js"):
            target = (static / manifest["paths"][original]).resolve()
            if not target.is_relative_to(static.resolve()) or not target.is_file():
                raise ValueError()
    except (OSError, ValueError, KeyError, TypeError):
        raise ImproperlyConfigured(
            "Run production collectstatic before starting this release."
        ) from None
