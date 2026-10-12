"""Actual PostgreSQL concurrency, worker restarts and fail-closed boundaries."""

import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.test import Client, SimpleTestCase, TransactionTestCase, override_settings

from config.environment import load_environment
from operations.models import RequestBudgetState
from operations.rate_limits import BudgetUnavailable, reserve
from research import services
from tests.test_environment import TEST_SECRET


class ReleaseConfigurationTests(SimpleTestCase):
    def production(self, **extra):
        return load_environment(
            {
                "DJANGO_ENV": "production",
                "DJANGO_SECRET_KEY": TEST_SECRET,
                "DJANGO_ALLOWED_HOSTS": "research.example.test",
                **extra,
            }
        )

    def test_production_requires_shared_limits_and_defaults_to_untrusted_proxy(self):
        current = self.production()
        self.assertEqual(current.rate_limit_backend, "postgresql")
        self.assertFalse(current.trust_proxy_https)
        for backend in ("memory", "private-fixture-value", "", "POSTGRESQL"):
            with self.assertRaises(ImproperlyConfigured) as error:
                self.production(DJANGO_RATE_LIMIT_BACKEND=backend)
            self.assertNotIn("private-fixture-value", str(error.exception))

    def test_development_can_choose_shared_limits_without_changing_default(self):
        self.assertEqual(load_environment({}).rate_limit_backend, "memory")
        self.assertEqual(
            load_environment({"DJANGO_RATE_LIMIT_BACKEND": "postgresql"}).rate_limit_backend,
            "postgresql",
        )

    def test_proxy_trust_is_explicit_validated_and_production_only(self):
        self.assertTrue(self.production(DJANGO_TRUST_PROXY_HTTPS="true").trust_proxy_https)
        with self.assertRaises(ImproperlyConfigured):
            load_environment({"DJANGO_TRUST_PROXY_HTTPS": "true"})
        with self.assertRaises(ImproperlyConfigured) as error:
            self.production(DJANGO_TRUST_PROXY_HTTPS="private-fixture-value")
        self.assertNotIn("private-fixture-value", str(error.exception))

    @override_settings(SECURE_SSL_REDIRECT=True, SECURE_PROXY_SSL_HEADER=None)
    def test_spoofed_forwarded_proto_is_ignored_by_default(self):
        response = self.client.get("/", HTTP_X_FORWARDED_PROTO="https")
        self.assertEqual(response.status_code, 301)
        self.assertTrue(response.headers["Location"].startswith("https://"))

    @override_settings(
        SECURE_SSL_REDIRECT=True,
        SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
        SECURE_HSTS_SECONDS=3600,
        CSRF_COOKIE_SECURE=True,
    )
    def test_configured_https_proxy_avoids_redirect_loop_and_sets_secure_cookie(self):
        response = self.client.get("/register/", HTTP_X_FORWARDED_PROTO="https")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Strict-Transport-Security"], "max-age=3600")
        self.assertTrue(response.cookies["csrftoken"]["secure"])
        self.assertEqual(self.client.get("/", HTTP_X_FORWARDED_PROTO="http").status_code, 301)


@skipUnless(connection.vendor == "postgresql", "Shared admission requires PostgreSQL")
@override_settings(RATE_LIMIT_BACKEND="postgresql")
class SharedBudgetTests(TransactionTestCase):
    def setUp(self):
        self.clock = patch("operations.rate_limits._database_now", return_value=65).start()
        self.addCleanup(patch.stopall)

    def test_exact_client_limit_retry_and_hash_only_storage(self):
        for _ in range(10):
            self.assertIsNone(reserve("market", "private-client-address"))
        self.assertEqual(reserve("market", "private-client-address"), 55)
        row = RequestBudgetState.objects.get(scope="market")
        self.assertEqual(row.total, 10)
        self.assertEqual(row.clients, {hashlib.sha256(b"private-client-address").hexdigest(): 10})

    def test_global_flood_is_bounded_and_does_not_store_denied_clients(self):
        for number in range(30):
            self.assertIsNone(reserve("market", str(number)))
        for number in range(100):
            self.assertEqual(reserve("market", f"denied-{number}"), 55)
        row = RequestBudgetState.objects.get(scope="market")
        self.assertEqual(row.total, 30)
        self.assertEqual(len(row.clients), 30)

    def test_auth_limits_are_shared_but_separate_from_provider_calls(self):
        for _ in range(10):
            self.assertIsNone(reserve("market", "one"))
            self.assertIsNone(reserve("auth", "one"))
        self.assertEqual(reserve("auth", "one"), 55)
        for number in range(50):
            self.assertIsNone(reserve("auth", str(number)))
        self.assertEqual(reserve("auth", "another"), 55)
        self.assertEqual(RequestBudgetState.objects.count(), 2)

    def test_rollover_and_backward_clock_do_not_refund_admission(self):
        for _ in range(10):
            reserve("market", "one")
        self.clock.return_value = 120
        self.assertIsNone(reserve("market", "one"))
        self.clock.return_value = 65
        for _ in range(9):
            self.assertIsNone(reserve("market", "one"))
        self.assertEqual(reserve("market", "one"), 115)
        self.assertEqual(RequestBudgetState.objects.get().window, 2)

    def test_one_row_creation_race_and_client_limit_are_atomic(self):
        def attempt(_):
            close_old_connections()
            try:
                return reserve("market", "same") is None
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=8) as workers:
            admitted = list(workers.map(attempt, range(30)))
        self.assertEqual(sum(admitted), 10)
        self.assertEqual(RequestBudgetState.objects.count(), 1)

    def test_concurrent_unique_clients_cannot_exceed_global_limit(self):
        def attempt(number):
            close_old_connections()
            try:
                return reserve("market", str(number)) is None
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=8) as workers:
            admitted = list(workers.map(attempt, range(50)))
        self.assertEqual(sum(admitted), 30)
        self.assertEqual(RequestBudgetState.objects.get().total, 30)

    def test_new_python_workers_do_not_get_new_allowances(self):
        database = connection.settings_dict
        environ = {
            **os.environ,
            "DJANGO_ENV": "development",
            "DJANGO_RATE_LIMIT_BACKEND": "postgresql",
            "DJANGO_DATABASE_ENGINE": "postgresql",
            **{
                "DJANGO_DATABASE_" + field: str(database[field])
                for field in ("NAME", "USER", "HOST", "PORT", "PASSWORD")
            },
            "DJANGO_DATABASE_SSLMODE": database["OPTIONS"]["sslmode"],
            "DJANGO_DATABASE_SSLROOTCERT": database["OPTIONS"].get("sslrootcert", ""),
        }
        script = Path(__file__).with_name("rate_limit_worker.py")
        results = []
        for _ in range(2):
            result = subprocess.run(
                [sys.executable, str(script)],
                env=environ,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            self.assertEqual(result.returncode, 0, "An isolated quota worker failed.")
            results.append(json.loads(result.stdout)["admitted"])
        self.assertEqual(results, [10, 0])

    def test_durable_reservation_cannot_be_rolled_back_by_a_business_transaction(self):
        with transaction.atomic(), self.assertRaises(BudgetUnavailable):
            reserve("market", "one")
        self.assertEqual(RequestBudgetState.objects.count(), 0)

    def test_database_failure_is_fixed_and_never_falls_back_to_local_memory(self):
        with (
            patch(
                "operations.rate_limits.RequestBudgetState.objects.get_or_create",
                side_effect=DatabaseError("private-fixture-value"),
            ),
            override_settings(INTRINIO_API_KEY="test-only-unused-key"),
            patch("research.services.IntrinioClient") as provider,
        ):
            response = self.client.get("/search/?q=AAPL")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(b"private-fixture-value", response.content)
        self.assertIn("no-store", response.headers["Cache-Control"])
        provider.assert_not_called()
        self.assertEqual(RequestBudgetState.objects.count(), 0)

    def test_all_account_writes_fail_closed_when_admission_storage_is_unavailable(self):
        owner = get_user_model().objects.create_user(
            "fixture-owner", password="Old-fixture-pass-94"
        )
        client = Client()
        client.force_login(owner)
        with patch("accounts.views.reserve_attempt", side_effect=BudgetUnavailable()):
            for route in ("/sign-in/", "/password/change/"):
                response = client.post(route, {"password": "private-fixture-value"})
                self.assertEqual(response.status_code, 503)
                self.assertNotIn(b"private-fixture-value", response.content)
                self.assertIn("no-store", response.headers["Cache-Control"])
            response = self.client.post("/register/", {"username": "unadmitted"})
            self.assertEqual(response.status_code, 503)
        self.assertEqual(get_user_model().objects.count(), 1)
        owner.refresh_from_db()
        self.assertTrue(owner.check_password("Old-fixture-pass-94"))

    def test_invalid_counter_state_fails_closed_instead_of_repairing_it(self):
        for clients, total in (([], 0), ({"not-a-hash": 1}, 1), ({"a" * 64: True}, 1), ({}, 1)):
            RequestBudgetState.objects.update_or_create(
                scope="market", defaults={"clients": clients, "total": total, "window": 1}
            )
            with self.assertRaises(BudgetUnavailable):
                reserve("market", "one")

    def test_network_work_occurs_after_the_reservation_transaction(self):
        with (
            override_settings(INTRINIO_API_KEY="test-only-unused-key"),
            patch("research.services.IntrinioClient") as provider,
        ):

            def checked_search(query):
                self.assertFalse(connection.in_atomic_block)
                self.assertEqual(RequestBudgetState.objects.get().total, 1)
                return query

            provider.return_value.__enter__.return_value.search.side_effect = checked_search
            self.assertEqual(services.search_securities("fixture", "one"), "fixture")
