"""Configuration failures must identify the requirement, never echo its value."""

import os
import subprocess
import sys
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from config.environment import load_environment

# Explicitly synthetic fixtures, never used by the running application.
TEST_SECRET = "test-only-not-a-real-credential-" * 3
TEST_API_KEY = "test-only-intrinio-key-never-send"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class EnvironmentTests(SimpleTestCase):
    def production_environment(self, **overrides):
        return {
            "DJANGO_ENV": "production",
            "DJANGO_SECRET_KEY": TEST_SECRET,
            "DJANGO_ALLOWED_HOSTS": "research.example.com",
            **overrides,
        }

    def test_development_has_local_hosts_and_an_ephemeral_secret(self):
        first = load_environment({})
        second = load_environment({})
        self.assertTrue(first.debug)
        self.assertFalse(first.production)
        self.assertEqual(first.allowed_hosts, ("localhost", "127.0.0.1", "[::1]"))
        self.assertGreaterEqual(len(first.secret_key), 50)
        self.assertNotEqual(first.secret_key, second.secret_key)

    def test_environment_repr_redacts_both_credentials(self):
        config = load_environment(
            {"DJANGO_SECRET_KEY": TEST_SECRET, "INTRINIO_API_KEY": TEST_API_KEY}
        )
        self.assertNotIn(TEST_SECRET, repr(config))
        self.assertNotIn(TEST_API_KEY, repr(config))

    def test_valid_production_defaults_to_debug_off(self):
        config = load_environment(self.production_environment())
        self.assertTrue(config.production)
        self.assertFalse(config.debug)

    def test_unknown_environment_is_rejected_without_echoing_it(self):
        with self.assertRaises(ImproperlyConfigured) as raised:
            load_environment({"DJANGO_ENV": TEST_API_KEY})
        self.assertNotIn(TEST_API_KEY, str(raised.exception))

    def test_production_rejects_debug(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "DJANGO_DEBUG must be false"):
            load_environment(self.production_environment(DJANGO_DEBUG="true"))

    def test_boolean_values_are_explicit(self):
        for value, expected in [(" true ", True), ("1", True), ("FALSE", False), ("0", False)]:
            with self.subTest(value=value):
                self.assertEqual(load_environment({"DJANGO_DEBUG": value}).debug, expected)
        with self.assertRaises(ImproperlyConfigured) as raised:
            load_environment({"DJANGO_DEBUG": TEST_API_KEY})
        self.assertNotIn(TEST_API_KEY, str(raised.exception))

    def test_production_rejects_missing_or_weak_secrets_without_echoing_them(self):
        for secret in ["", "short-test-secret", "a" * 80, "django-insecure-" + TEST_SECRET]:
            with self.subTest(length=len(secret)):
                with self.assertRaises(ImproperlyConfigured) as raised:
                    load_environment(self.production_environment(DJANGO_SECRET_KEY=secret))
                self.assertIn("DJANGO_SECRET_KEY", str(raised.exception))
                if secret:
                    self.assertNotIn(secret, str(raised.exception))

    def test_production_requires_explicit_hosts(self):
        environ = self.production_environment()
        del environ["DJANGO_ALLOWED_HOSTS"]
        with self.assertRaisesMessage(ImproperlyConfigured, "DJANGO_ALLOWED_HOSTS"):
            load_environment(environ)

    def test_rejects_wildcards_urls_ports_and_invalid_hosts(self):
        for hosts in [
            "",
            "*",
            "localhost,*",
            "https://research.example.com",
            "localhost:8000",
            "research.example.com/path",
            "bad host",
            "[invalid]",
            "-bad.example",
        ]:
            with self.subTest(hosts=hosts):
                with self.assertRaises(ImproperlyConfigured):
                    load_environment({"DJANGO_ALLOWED_HOSTS": hosts})

    def test_accepts_explicit_hostnames_and_ipv6(self):
        config = load_environment({"DJANGO_ALLOWED_HOSTS": "localhost, 127.0.0.1, [::1]"})
        self.assertEqual(config.allowed_hosts, ("localhost", "127.0.0.1", "[::1]"))

    def test_missing_provider_key_does_not_prevent_development(self):
        self.assertEqual(load_environment({}).intrinio_api_key, "")


class StartupTests(SimpleTestCase):
    def run_process(self, args, **overrides):
        # Inherit runtime/proxy bindings, while isolating only application settings.
        environ = {
            name: value
            for name, value in os.environ.items()
            if not name.startswith(("DJANGO_", "INTRINIO_"))
        }
        environ.update(overrides)
        return subprocess.run(
            [sys.executable, *args],
            cwd=PROJECT_ROOT,
            env=environ,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

    def test_real_django_startup_rejects_missing_production_secret(self):
        result = self.run_process(
            ["manage.py", "check"],
            DJANGO_ENV="production",
            DJANGO_ALLOWED_HOSTS="research.example.com",
            DJANGO_DATABASE_ENGINE="postgresql",
            DJANGO_DATABASE_NAME="fixture_database",
            DJANGO_DATABASE_USER="fixture_user",
            DJANGO_DATABASE_HOST="fixture.database.example",
            DJANGO_DATABASE_PASSWORD="fixture-only-not-a-real-password",
            INTRINIO_API_KEY=TEST_API_KEY,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DJANGO_SECRET_KEY", result.stderr)
        self.assertNotIn(TEST_API_KEY, result.stdout + result.stderr)

    def test_real_django_startup_applies_production_security(self):
        script = (
            "import django; django.setup(); from django.conf import settings; "
            "assert settings.DEBUG is False; assert settings.SECURE_SSL_REDIRECT; "
            "assert settings.SESSION_COOKIE_SECURE; assert settings.CSRF_COOKIE_SECURE; "
            "assert settings.SESSION_COOKIE_HTTPONLY; assert settings.X_FRAME_OPTIONS == 'DENY'"
        )
        result = self.run_process(
            ["-c", script],
            DJANGO_SETTINGS_MODULE="config.settings",
            DJANGO_ENV="production",
            DJANGO_SECRET_KEY=TEST_SECRET,
            DJANGO_ALLOWED_HOSTS="research.example.com",
            DJANGO_DATABASE_ENGINE="postgresql",
            DJANGO_DATABASE_NAME="fixture_database",
            DJANGO_DATABASE_USER="fixture_user",
            DJANGO_DATABASE_HOST="fixture.database.example",
            DJANGO_DATABASE_PASSWORD="fixture-only-not-a-real-password",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
