"""Validated settings; deployment still requires verified hosting and ingress."""

import os
from pathlib import Path

from config.database import database_settings
from config.environment import load_environment

BASE_DIR = Path(__file__).resolve().parent.parent
ENVIRONMENT = load_environment(os.environ)

SECRET_KEY = ENVIRONMENT.secret_key
DEBUG = ENVIRONMENT.debug
ALLOWED_HOSTS = list(ENVIRONMENT.allowed_hosts)
INTRINIO_API_KEY = ENVIRONMENT.intrinio_api_key
RATE_LIMIT_BACKEND = ENVIRONMENT.rate_limit_backend
PRIVATE_SITE = ENVIRONMENT.private_site
ALLOW_REGISTRATION = ENVIRONMENT.allow_registration

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "research",
    "portfolios",
    "ledger",
    "watchlists",
    "operations",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "config.middleware.ResponsePolicyMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "portfolios.holdings_uploads.HoldingsUploadMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "config.middleware.PrivateSiteMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "accounts.context_processors.registration_policy",
            ]
        },
    }
]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# SQLite still supports the research/account foundation. Private portfolios
# explicitly require PostgreSQL, and production must never fall back to SQLite.
DATABASES = {"default": database_settings(os.environ, BASE_DIR, production=ENVIRONMENT.production)}
AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "sign_in"
LOGIN_REDIRECT_URL = "account"
LOGOUT_REDIRECT_URL = "home"
# Idle sessions expire after eight hours; active use refreshes the expiry.
SESSION_COOKIE_AGE = 8 * 60 * 60
SESSION_SAVE_EVERY_REQUEST = True
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "whitenoise.storage.CompressedManifestStaticFilesStorage"
            if ENVIRONMENT.production
            else "django.contrib.staticfiles.storage.StaticFilesStorage"
        )
    },
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Opt in only after ingress strips/replaces this header and direct access is blocked.
SECURE_PROXY_SSL_HEADER = (
    ("HTTP_X_FORWARDED_PROTO", "https") if ENVIRONMENT.trust_proxy_https else None
)
SECURE_SSL_REDIRECT = ENVIRONMENT.production
# This fixed process-only response contains no user/provider/storage information.
SECURE_REDIRECT_EXEMPT = [r"^health/live/$"]
SESSION_COOKIE_SECURE = ENVIRONMENT.production
CSRF_COOKIE_SECURE = ENVIRONMENT.production
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
# Short HSTS initially; expand only after the deployment's HTTPS is validated.
SECURE_HSTS_SECONDS = 3600 if ENVIRONMENT.production else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"redact_provider_secrets": {"()": "market_data.logging.SecretRedactionFilter"}},
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "filters": ["redact_provider_secrets"],
        }
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        # Successful account URLs can contain usernames/return destinations;
        # avoid routine request/access logging by Django's development server.
        "django.server": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        # The logger-level filter also protects attached diagnostic handlers.
        "httpx": {"level": "WARNING", "filters": ["redact_provider_secrets"]},
        "httpcore": {"level": "WARNING"},
        "research": {"level": "WARNING", "filters": ["redact_provider_secrets"]},
    },
}
