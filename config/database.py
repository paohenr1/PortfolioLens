"""Explicit database settings; malformed configuration never silently uses SQLite."""

import re
from collections.abc import Mapping
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,62}\Z")
_HOST = re.compile(r"[A-Za-z0-9.-]{1,253}\Z")


def database_settings(environ: Mapping[str, str], base_dir: Path, *, production: bool):
    engine = environ.get("DJANGO_DATABASE_ENGINE", "sqlite").strip().lower()
    if engine == "sqlite":
        if production:
            raise ImproperlyConfigured("Production requires DJANGO_DATABASE_ENGINE=postgresql.")
        if any(
            environ.get(name)
            for name in environ
            if name.startswith("DJANGO_DATABASE_") and name != "DJANGO_DATABASE_ENGINE"
        ):
            raise ImproperlyConfigured(
                "PostgreSQL options require DJANGO_DATABASE_ENGINE=postgresql."
            )
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": base_dir / "db.sqlite3"}
    if engine != "postgresql":
        raise ImproperlyConfigured("DJANGO_DATABASE_ENGINE must be sqlite or postgresql.")

    values = {}
    for name in ("NAME", "USER", "HOST"):
        value = environ.get(f"DJANGO_DATABASE_{name}", "").strip()
        if not value:
            raise ImproperlyConfigured(f"DJANGO_DATABASE_{name} is required for PostgreSQL.")
        values[name] = value
    if any(not _IDENTIFIER.fullmatch(values[name]) for name in ("NAME", "USER")):
        raise ImproperlyConfigured("Database name and user must be simple PostgreSQL identifiers.")
    host = values["HOST"]
    local_socket = host.startswith("/")
    if (local_socket and ("\x00" in host or ".." in Path(host).parts)) or (
        not local_socket and not _HOST.fullmatch(host)
    ):
        raise ImproperlyConfigured(
            "DJANGO_DATABASE_HOST must be a hostname, IPv4, or socket directory."
        )
    port = environ.get("DJANGO_DATABASE_PORT", "5432").strip()
    if not port.isascii() or not port.isdecimal() or not 1 <= int(port) <= 65535:
        raise ImproperlyConfigured("DJANGO_DATABASE_PORT must be between 1 and 65535.")
    if local_socket and len(f"{host}/.s.PGSQL.{port}".encode()) > 107:
        raise ImproperlyConfigured("DJANGO_DATABASE_HOST exceeds the Unix socket path limit.")
    sslmode = environ.get("DJANGO_DATABASE_SSLMODE", "verify-full" if production else "disable")
    if sslmode not in {"disable", "require", "verify-ca", "verify-full"}:
        raise ImproperlyConfigured("DJANGO_DATABASE_SSLMODE is unsupported.")
    password = environ.get("DJANGO_DATABASE_PASSWORD", "")
    if production and (local_socket or not password or sslmode != "verify-full"):
        raise ImproperlyConfigured(
            "Production PostgreSQL requires a password, TCP host, and verify-full TLS."
        )
    options = {"connect_timeout": 5, "sslmode": sslmode}
    certificate = environ.get("DJANGO_DATABASE_SSLROOTCERT", "").strip()
    if certificate:
        options["sslrootcert"] = certificate
    return {
        "ENGINE": "django.db.backends.postgresql",
        **values,
        "PORT": port,
        "PASSWORD": password,
        "CONN_MAX_AGE": 0,
        "OPTIONS": options,
    }
