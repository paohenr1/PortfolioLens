"""Production privacy, process-only probes and reviewed serving configuration."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, TestCase, override_settings

from config.environment import load_environment
from deploy.runtime import check_static_release, gunicorn_options
from tests.test_environment import TEST_SECRET


def configured(**extra):
    return {
        "DJANGO_ENV": "production",
        "DJANGO_SECRET_KEY": TEST_SECRET,
        "DJANGO_ALLOWED_HOSTS": "research.example.test",
        "DJANGO_DATABASE_ENGINE": "postgresql",
        "DJANGO_DATABASE_NAME": "fixture_database",
        "DJANGO_DATABASE_USER": "fixture_user",
        "DJANGO_DATABASE_HOST": "db.example.test",
        "DJANGO_DATABASE_PASSWORD": "synthetic-only-password",
        **extra,
    }


class ProductionRuntimeTests(SimpleTestCase):
    def test_production_defaults_to_private_site_and_closed_registration(self):
        current = load_environment(configured())
        self.assertTrue(current.private_site)
        self.assertFalse(current.allow_registration)
        local = load_environment({})
        self.assertFalse(local.private_site)
        self.assertTrue(local.allow_registration)

    def test_access_policy_is_explicit_and_invalid_values_are_redacted(self):
        current = load_environment(
            configured(DJANGO_PRIVATE_SITE="false", DJANGO_ALLOW_REGISTRATION="true")
        )
        self.assertFalse(current.private_site)
        self.assertTrue(current.allow_registration)
        for name in ("DJANGO_PRIVATE_SITE", "DJANGO_ALLOW_REGISTRATION"):
            with self.assertRaises(ImproperlyConfigured) as error:
                load_environment(configured(**{name: "private-fixture-value"}))
            self.assertNotIn("private-fixture-value", str(error.exception))

    def test_gunicorn_defaults_do_not_implicitly_trust_proxy_headers(self):
        options = gunicorn_options(configured())
        self.assertEqual(options["bind"], "127.0.0.1:8000")
        self.assertEqual(options["workers"], 1)
        self.assertEqual(options["forwarded_allow_ips"], "")
        self.assertEqual(options["secure_scheme_headers"], {})
        self.assertIsNone(options["accesslog"])
        self.assertFalse(options["preload_app"])

    def test_serving_rejects_development_weak_database_and_hidden_cli_overrides(self):
        for extra in (
            {"DJANGO_ENV": "development"},
            {"DJANGO_DATABASE_SSLMODE": "disable"},
            {"GUNICORN_CMD_ARGS": "--reload"},
            {"STOCK_BIND_HOST": "private-fixture-value"},
        ):
            with self.assertRaises(ImproperlyConfigured) as error:
                gunicorn_options(configured(**extra))
            self.assertNotIn("private-fixture-value", str(error.exception))

    def test_bind_and_worker_limits_are_bounded_before_server_start(self):
        for extra in (
            {"PORT": "0"},
            {"PORT": "65536"},
            {"PORT": "8000 --reload"},
            {"PORT": "1" * 5000},
            {"PORT": "٨٠٠٠"},
            {"STOCK_WORKERS": "0"},
            {"STOCK_WORKERS": "999"},
        ):
            with self.assertRaises(ImproperlyConfigured):
                gunicorn_options(configured(**extra))
        self.assertEqual(
            gunicorn_options(configured(PORT="10000", STOCK_BIND_HOST="0.0.0.0"))["bind"],
            "0.0.0.0:10000",
        )

    def test_missing_and_malformed_static_artifacts_refuse_serving(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ImproperlyConfigured):
                check_static_release(root)
            static = root / "staticfiles"
            static.mkdir()
            (static / "staticfiles.json").write_text('{"paths":null}')
            with self.assertRaises(ImproperlyConfigured):
                check_static_release(root)

    def test_manifest_must_contain_real_files_inside_the_static_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root, original = Path(directory), ("research/site.css", "research/prices.js")
            static = root / "staticfiles"
            static.mkdir()
            paths = {}
            for index, name in enumerate(original):
                paths[name] = f"asset-{index}.hash"
                (static / paths[name]).write_text("synthetic asset")
            manifest = static / "staticfiles.json"
            manifest.write_text(json.dumps({"paths": paths}))
            check_static_release(root)
            (root / "outside").write_text("synthetic outside file")
            paths[original[0]] = "../outside"
            manifest.write_text(json.dumps({"paths": paths}))
            with self.assertRaises(ImproperlyConfigured):
                check_static_release(root)


@override_settings(PRIVATE_SITE=True, ALLOW_REGISTRATION=False)
class PrivateAnonymousTests(SimpleTestCase):
    def test_research_gets_redirect_before_any_provider_or_database_work(self):
        with patch("research.services.IntrinioClient", side_effect=AssertionError):
            for route in (
                "/",
                "/search/?q=AAPL",
                "/stocks/sec_fixture_primary/",
                "/stocks/sec_fixture_primary/prices/?start_date=2020-01-02",
            ):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.headers["Location"].startswith("/sign-in/?next="))
                self.assertIn("no-store", response.headers["Cache-Control"])

    def test_closed_registration_get_and_post_do_not_create_records_or_spend_attempts(self):
        with patch("accounts.views.reserve_attempt", side_effect=AssertionError):
            self.assertEqual(self.client.get("/register/").status_code, 404)
            self.assertEqual(
                self.client.post("/register/", {"username": "unadmitted"}).status_code, 404
            )

    def test_signin_is_available_and_does_not_advertise_closed_registration(self):
        response = self.client.get("/sign-in/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "csrfmiddlewaretoken")
        self.assertNotContains(response, 'href="/register/"')

    @override_settings(SECURE_SSL_REDIRECT=True)
    def test_health_is_process_only_and_plain_http_exemption_is_narrow(self):
        with patch("research.services.IntrinioClient", side_effect=AssertionError):
            response = self.client.get("/health/live/")
            self.assertEqual(response.json(), {"status": "alive"})
            self.assertIn("no-store", response.headers["Cache-Control"])
            self.assertEqual(self.client.head("/health/live/").content, b"")
            self.assertEqual(self.client.post("/health/live/").status_code, 405)
            self.assertEqual(self.client.get("/").status_code, 301)


@override_settings(PRIVATE_SITE=True, ALLOW_REGISTRATION=False)
class PrivateSessionTests(TestCase):
    def test_active_session_can_reach_research_but_logout_closes_it(self):
        owner = get_user_model().objects.create_user("private-serving-fixture")
        self.client.force_login(owner)
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/search/").status_code, 200)
        self.assertRedirects(self.client.get("/register/"), "/account/")
        self.client.post("/sign-out/")
        self.assertEqual(self.client.get("/").status_code, 302)

    def test_disabled_user_does_not_keep_private_research_access(self):
        owner = get_user_model().objects.create_user("disabled-serving-fixture")
        self.client.force_login(owner)
        owner.is_active = False
        owner.save(update_fields=("is_active",))
        self.assertEqual(self.client.get("/search/").status_code, 302)
