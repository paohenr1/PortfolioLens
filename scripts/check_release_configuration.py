"""Check production configuration with temporary synthetic values, without network."""

import os
import secrets
import subprocess
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent.parent
    # Clear only app settings in this child, preserving proxy/CA/runtime bindings.
    environ = {key: value for key, value in os.environ.items() if not key.startswith("DJANGO_")}
    environ.update(
        DJANGO_ENV="production",
        DJANGO_SECRET_KEY=secrets.token_urlsafe(64),
        DJANGO_ALLOWED_HOSTS="release.example.test",
        DJANGO_DATABASE_ENGINE="postgresql",
        DJANGO_DATABASE_NAME="synthetic_release_database",
        DJANGO_DATABASE_USER="synthetic_release_user",
        DJANGO_DATABASE_HOST="database.example.test",
        DJANGO_DATABASE_PASSWORD="synthetic-only-not-a-real-database-password",
        DJANGO_DATABASE_SSLMODE="verify-full",
        INTRINIO_API_KEY="",
    )
    script = """
import django
django.setup()
from django.conf import settings
from django.core.checks import WARNING, run_checks
# Keep the actual Django findings visible. Do not force HSTS onto unverified
# sibling domains or enroll a not-yet-deployed hostname in browser preload lists.
assert settings.SECURE_HSTS_INCLUDE_SUBDOMAINS is False
assert settings.SECURE_HSTS_PRELOAD is False
assert settings.RATE_LIMIT_BACKEND == 'postgresql'
assert settings.SECURE_PROXY_SSL_HEADER is None
assert settings.PRIVATE_SITE is True
assert settings.ALLOW_REGISTRATION is False
accepted = {'security.W005', 'security.W021'}
findings = run_checks(include_deployment_checks=True)
for finding in findings:
    if finding.level >= WARNING:
        print(finding.id, str(finding))
unexpected = [f for f in findings if f.level >= WARNING and f.id not in accepted]
raise SystemExit(1 if unexpected else 0)
"""
    environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
    subprocess.run(
        [sys.executable, "-c", script],
        env=environ,
        cwd=root,
        check=True,
        timeout=30,
    )
    print("Production checks: no unexpected findings; two intentional HSTS policies retained.")
    print("Hosted database TLS, HTTPS ingress and deployment remain unverified.")


if __name__ == "__main__":
    main()
