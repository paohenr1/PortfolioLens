"""Private price loads, exact-date transport, shared budget and no business writes."""

import uuid
from decimal import Decimal
from unittest import skipUnless
from unittest.mock import patch

import httpx
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from market_data.errors import ProviderRateLimited
from market_data.intrinio import IntrinioClient
from portfolios.models import HoldingsSnapshot, SnapshotHolding
from portfolios.snapshot_services import delete_snapshot, save_snapshot
from research import services as market_data
from tests.test_intrinio import TEST_KEY
from tests.test_snapshot_contracts import raw_token, verified
from tests.test_snapshot_review import AS_OF, history


@skipUnless(connection.vendor == "postgresql", "Snapshot review requires PostgreSQL")
class SnapshotReviewPagesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = get_user_model().objects.create_user("review-alice")
        cls.bob = get_user_model().objects.create_user("review-bob")
        cls.snapshot = save_snapshot(
            user=cls.alice, token=raw_token(verified(cls.alice)), confirmed=True
        )
        cls.identifier = cls.snapshot.holdings.get().security_id

    def setUp(self):
        self.client.force_login(self.alice)
        self.url = reverse("snapshot_review", args=[self.snapshot.pk])
        self.prices_patch = patch.object(
            market_data, "daily_prices", return_value=history(self.identifier)
        )
        self.prices = self.prices_patch.start()
        self.addCleanup(self.prices_patch.stop)

    def load(self, **data):
        return self.client.post(self.url, {"action": "load", **data})

    def extra(self, identifier):
        SnapshotHolding.objects.create(
            snapshot=self.snapshot,
            security_id=identifier,
            ticker="OTHER",
            exchange_mic="XNAS",
            quantity="2",
            reference_retrieved_at=history().retrieved_at,
        )

    def test_get_flags_empty_post_and_unsafe_methods_spend_no_requests(self):
        response = self.client.get(self.url, {"action": "load", "load": "1"})
        self.assertContains(response, "No review loaded")
        self.assertIsNone(response.context["review"])
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(self.client.post(self.url).status_code, 400)
        for method in ("put", "patch", "delete", "head"):
            self.assertEqual(getattr(self.client, method)(self.url).status_code, 405)
        self.prices.assert_not_called()

    def test_fixed_date_repeat_loads_no_saved_results_no_ledger_access(self):
        from portfolios.models import SnapshotSubmission

        before = (
            list(HoldingsSnapshot.objects.values()),
            list(SnapshotHolding.objects.values()),
            list(SnapshotSubmission.objects.values()),
        )
        with CaptureQueriesContext(connection) as queries:
            response = self.load(as_of="2099-01-02", cash="999", quantity="999")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Holdings snapshot review · 2020-01-02")
        self.assertEqual(response.context["review"].total_value, Decimal("32.34"))
        self.assertEqual(response.context["review"].cash, Decimal("12.34"))
        self.prices.assert_called_once_with(self.identifier, AS_OF, "127.0.0.1")
        self.assertEqual(
            before,
            (
                list(HoldingsSnapshot.objects.values()),
                list(SnapshotHolding.objects.values()),
                list(SnapshotSubmission.objects.values()),
            ),
        )
        for query in queries:
            self.assertNotRegex(query["sql"], r"(?i)(ledger_|watchlists_|portfolios_portfolio)")
            if "portfolios_" in query["sql"].lower():
                self.assertNotRegex(query["sql"], r"(?i)^\s*(insert|update|delete)")
        self.prices.return_value = history(self.identifier, "10")
        self.assertEqual(self.load().context["review"].total_value, Decimal("22.34"))
        self.assertEqual(self.prices.call_count, 2)
        self.assertIsNone(self.client.get(self.url).context["review"])

    def test_foreign_missing_anonymous_inactive_and_csrf_block_provider(self):
        self.client.force_login(self.bob)
        for url in (self.url, reverse("snapshot_review", args=[uuid.uuid4()])):
            for method in ("get", "post"):
                response = getattr(self.client, method)(url, {"action": "load"})
                self.assertEqual(response.status_code, 404)
                self.assertIn("no-store", response.headers["Cache-Control"])
                self.assertNotContains(response, self.snapshot.name, status_code=404)
        self.client.logout()
        self.assertEqual(self.load().status_code, 302)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.alice)
        self.assertEqual(client.post(self.url, {"action": "load"}).status_code, 403)
        self.alice.is_active = False
        self.alice.save(update_fields=["is_active"])
        self.client.force_login(self.alice)
        self.assertEqual(self.load().status_code, 302)
        self.prices.assert_not_called()

    def test_cash_only_needs_no_quotes_and_concentration_is_not_applicable(self):
        snapshot = save_snapshot(
            user=self.alice, token=raw_token(verified(self.alice, cash_only=True)), confirmed=True
        )
        response = self.client.post(
            reverse("snapshot_review", args=[snapshot.pk]), {"action": "load"}
        )
        self.assertContains(response, "Cash-only snapshot")
        self.assertContains(response, "100.00%")
        self.assertContains(response, "Not applicable")
        self.prices.assert_not_called()

    def test_incomplete_and_zero_valuations_do_not_invent_a_denominator(self):
        self.extra("zz_second")
        self.prices.side_effect = [history(self.identifier), history("zz_second", None)]
        response = self.load()
        self.assertEqual(response.status_code, 200)
        result = response.context["review"]
        self.assertEqual(result.priced_count, 1)
        self.assertIsNone(result.total_value)
        self.assertContains(response, "1 of 2")
        self.assertContains(response, "No confirmed raw USD close")
        self.assertTrue(all(row.weight is None for row in result.rows))
        HoldingsSnapshot.objects.filter(pk=self.snapshot.pk).update(cash=0)
        self.prices.side_effect = [history(self.identifier, "0"), history("zz_second", "0")]
        response = self.load()
        self.assertContains(response, "total value is zero")
        self.assertEqual(response.context["review"].total_value, Decimal("0.00"))

    def test_rate_limit_stops_remaining_rows_and_safe_other_failures_preserve_known_values(self):
        for key in ("zz_second", "zz_third"):
            self.extra(key)
        self.prices.side_effect = [history(self.identifier), ProviderRateLimited(23)]
        response = self.load()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["Retry-After"], "23")
        self.assertEqual(self.prices.call_count, 2)
        self.assertEqual(response.context["review"].priced_count, 1)
        self.assertContains(response, "Not requested", status_code=429)
        self.prices.reset_mock()
        self.prices.side_effect = [
            RuntimeError("SECRET authenticated URL"),
            history("zz_second"),
            history("zz_third"),
        ]
        with self.assertLogs("research", level="ERROR") as logs:
            response = self.load()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.context["review"].priced_count, 2)
        self.assertNotContains(response, "SECRET", status_code=503)
        self.assertNotIn("SECRET", str(logs.output))

    def test_corrupt_stored_inputs_and_more_than_five_fail_before_requests(self):
        for key in ("b", "c", "d", "e", "f"):
            self.extra(key)
        response = self.load()
        self.assertEqual(response.status_code, 503)
        self.prices.assert_not_called()
        SnapshotHolding.objects.filter(snapshot=self.snapshot).exclude(
            security_id=self.identifier
        ).delete()
        for updates in ({"exchange_mic": "XTST"}, {"security_id": "bad/id"}):
            row = self.snapshot.holdings.get()
            original = {key: getattr(row, key) for key in updates}
            SnapshotHolding.objects.filter(pk=row.pk).update(**updates)
            self.assertEqual(self.load().status_code, 503)
            SnapshotHolding.objects.filter(pk=row.pk).update(**original)
        HoldingsSnapshot.objects.filter(pk=self.snapshot.pk).update(as_of="2020-01-04")
        self.assertEqual(self.load().status_code, 503)
        self.prices.assert_not_called()

    def test_delete_during_price_load_prevents_showing_result(self):
        def delete_during_load(*args):
            delete_snapshot(user=self.alice, snapshot_id=self.snapshot.pk)
            return history(self.identifier)

        self.prices.side_effect = delete_during_load
        self.assertEqual(self.load().status_code, 404)
        self.assertFalse(SnapshotHolding.objects.filter(snapshot_id=self.snapshot.pk).exists())

    def test_five_holdings_use_at_most_five_requests(self):
        for key in "abcd":
            self.extra(key)
        self.prices.side_effect = lambda identifier, *args: history(identifier)
        response = self.load()
        self.assertEqual(response.context["review"].priced_count, 5)
        self.assertEqual(self.prices.call_count, 5)

    def test_name_and_ticker_are_escaped(self):
        HoldingsSnapshot.objects.filter(pk=self.snapshot.pk).update(name="<script>private</script>")
        SnapshotHolding.objects.filter(snapshot=self.snapshot).update(
            ticker="<script>ticker</script>"
        )
        response = self.load()
        self.assertContains(response, "&lt;script&gt;private&lt;/script&gt;")
        self.assertContains(response, "&lt;script&gt;ticker&lt;/script&gt;")
        self.assertNotContains(response, "<script>")

    @override_settings(INTRINIO_API_KEY=TEST_KEY, RATE_LIMIT_BACKEND="memory")
    def test_actual_daily_adapter_exact_date_one_page_shared_budget_no_reference_lookup(self):
        self.prices_patch.stop()
        market_data._request_budget.reset()
        self.addCleanup(market_data._request_budget.reset)
        calls = []

        def transport(request):
            calls.append(request)
            self.assertEqual(request.url.path, f"/securities/{self.identifier}/prices")
            self.assertEqual(request.url.params["start_date"], "2020-01-02")
            self.assertEqual(request.url.params["end_date"], "2020-01-02")
            self.assertNotIn("next_page", request.url.params)
            return httpx.Response(
                200,
                json={
                    "security": {
                        "id": self.identifier,
                        "ticker": "TSTF",
                        "exchange_mic": "XNAS",
                        "currency": "USD",
                    },
                    "stock_prices": [
                        {"date": "2020-01-02", "close": 20, "adj_close": 999, "intraperiod": False}
                    ],
                    "next_page": "remaining-cursor",
                },
            )

        with patch.object(
            market_data,
            "IntrinioClient",
            side_effect=lambda key: IntrinioClient(key, transport=httpx.MockTransport(transport)),
        ):
            response = self.load()
            self.assertEqual(len(calls), 1)
            self.assertIsNone(response.context["review"].total_value)
            for _ in range(9):
                market_data._request_budget.reserve("127.0.0.1")
            response = self.load()
            self.assertEqual(response.status_code, 429)
            self.assertEqual(len(calls), 1)


@skipUnless(connection.vendor != "postgresql", "SQLite fallback only")
class SnapshotReviewUnavailableTests(TestCase):
    def test_postgresql_is_required(self):
        user = get_user_model().objects.create_user("review-unavailable")
        self.client.force_login(user)
        url = reverse("snapshot_review", args=[uuid.uuid4()])
        self.assertEqual(self.client.get(url).status_code, 503)
        self.assertEqual(self.client.post(url, {"action": "load"}).status_code, 503)


@skipUnless(connection.vendor == "postgresql", "Review locking requires PostgreSQL")
class SnapshotReviewTransactionTests(TransactionTestCase):
    def test_price_io_runs_after_transaction_and_concurrent_delete_leaves_no_result(self):
        from concurrent.futures import ThreadPoolExecutor

        from django.db import close_old_connections
        from django.http import Http404

        from portfolios import snapshot_review_services

        owner = get_user_model().objects.create_user("review-transaction")
        snapshot = save_snapshot(user=owner, token=raw_token(verified(owner)), confirmed=True)
        identifier = snapshot.holdings.get().security_id

        def delete_in_other_connection():
            close_old_connections()
            try:
                current_owner = get_user_model().objects.get(pk=owner.pk)
                delete_snapshot(user=current_owner, snapshot_id=snapshot.pk)
            finally:
                close_old_connections()

        def price_after_delete(*args):
            self.assertFalse(connection.in_atomic_block)
            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(delete_in_other_connection).result(timeout=5)
            return history(identifier)

        with patch.object(market_data, "daily_prices", side_effect=price_after_delete):
            with self.assertRaises(Http404):
                snapshot_review_services.load_review(owner, snapshot.pk, "127.0.0.1")
        self.assertFalse(HoldingsSnapshot.objects.filter(pk=snapshot.pk).exists())

    def test_disabled_owner_during_io_cannot_receive_review(self):
        from django.http import Http404

        from portfolios import snapshot_review_services

        owner = get_user_model().objects.create_user("review-disabled")
        snapshot = save_snapshot(user=owner, token=raw_token(verified(owner)), confirmed=True)
        identifier = snapshot.holdings.get().security_id

        def disable(*args):
            get_user_model().objects.filter(pk=owner.pk).update(is_active=False)
            return history(identifier)

        with patch.object(market_data, "daily_prices", side_effect=disable):
            with self.assertRaises(Http404):
                snapshot_review_services.load_review(owner, snapshot.pk, "127.0.0.1")
