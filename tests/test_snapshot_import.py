"""Synthetic contracts, bounded resolution, private persistence and retry races."""

import uuid
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase
from django.urls import reverse

from market_data.errors import ProviderRateLimited
from portfolios import snapshot_services as services
from portfolios.models import HoldingsSnapshot, Portfolio
from portfolios.services import PortfolioStorageUnavailable
from research import services as market_data
from tests.test_holdings_csv import upload
from tests.test_snapshot_contracts import (
    REFERENCE,
    SEARCH,
    SECURITY,
    initial,
    matched,
    raw_token,
    verified,
)


@skipUnless(connection.vendor == "postgresql", "Snapshots require PostgreSQL")
class SnapshotViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = get_user_model().objects.create_user("snapshot-web-alice")
        cls.bob = get_user_model().objects.create_user("snapshot-web-bob")

    def setUp(self):
        self.client.force_login(self.alice)
        self.url = reverse("snapshot_import")
        self.payload = verified(self.alice)

    def post(self, action, payload, **data):
        return self.client.post(self.url, {"action": action, "preview": raw_token(payload), **data})

    def test_full_workflow_explicit_selection_confirmation_and_no_get_provider(self):
        response = self.client.post(
            reverse("holdings_preview"),
            {"name": "Workflow", "as_of": "2020-01-02", "cash": "0", "holdings_file": upload()},
        )
        token = response.context["snapshot_token"]
        with (
            patch.object(market_data, "search_securities", return_value=SEARCH) as search,
            patch.object(market_data, "security_details", return_value=REFERENCE) as details,
        ):
            self.assertEqual(
                self.client.get(self.url, {"preview": token, "action": "find"}).status_code, 405
            )
            search.assert_not_called()
            found = self.client.post(self.url, {"preview": token, "action": "find"})
            self.assertContains(found, "Choose an instrument")
            details.assert_not_called()
            selected = self.client.post(
                self.url,
                {"preview": found.context["token"], "action": "verify", "holding_0": SECURITY.id},
            )
            self.assertContains(selected, "Confirm snapshot inputs")
            self.assertFalse(HoldingsSnapshot.objects.exists())
            data = {"preview": selected.context["token"], "action": "save"}
            self.assertEqual(self.client.post(self.url, data).status_code, 400)
            saved = self.client.post(self.url, {**data, "confirmed": "on"})
            snapshot = HoldingsSnapshot.objects.get()
            self.assertRedirects(saved, reverse("snapshot_detail", args=[snapshot.pk]))
            self.assertRedirects(self.client.post(self.url, {**data, "confirmed": "on"}), saved.url)
            search.assert_called_once()
            details.assert_called_once()
        self.assertEqual(Portfolio.objects.count(), 0)

    def test_private_lists_foreign_ids_delete_confirmation_and_methods(self):
        saved = services.save_snapshot(
            user=self.alice, token=raw_token(self.payload), confirmed=True
        )
        detail = reverse("snapshot_detail", args=[saved.pk])
        delete = reverse("snapshot_delete", args=[saved.pk])
        for method, url in (("get", detail), ("get", delete), ("get", reverse("snapshot_list"))):
            response = getattr(self.client, method)(url)
            self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(self.client.post(detail).status_code, 405)
        self.assertEqual(self.client.post(delete).status_code, 400)
        self.assertTrue(HoldingsSnapshot.objects.exists())
        self.client.force_login(self.bob)
        self.assertNotContains(self.client.get(reverse("snapshot_list")), saved.name)
        for method, url in (("get", detail), ("get", delete), ("post", delete)):
            response = getattr(self.client, method)(url)
            self.assertEqual(response.status_code, 404)
            self.assertIn("no-store", response.headers["Cache-Control"])
        response = self.post("save", self.payload, confirmed="on")
        self.assertEqual(response.status_code, 400)
        self.assertNotContains(response, saved.name, status_code=400)
        self.client.force_login(self.alice)
        self.assertRedirects(
            self.client.post(delete, {"confirmed": "on"}), reverse("snapshot_list")
        )
        self.assertEqual(self.post("save", self.payload, confirmed="on").status_code, 400)
        self.assertFalse(HoldingsSnapshot.objects.exists())

    def test_auth_csrf_and_escaping(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.alice)
        self.assertEqual(
            client.post(
                self.url, {"preview": raw_token(self.payload), "action": "save", "confirmed": "on"}
            ).status_code,
            403,
        )
        self.payload["name"] = "<script>private</script>"
        self.payload["rows"][0]["reference"]["name"] = "<script>provider</script>"
        self.post("save", self.payload, confirmed="on")
        saved = HoldingsSnapshot.objects.get()
        detail = reverse("snapshot_detail", args=[saved.pk])
        response = self.client.get(detail)
        self.assertContains(response, "&lt;script&gt;private&lt;/script&gt;")
        self.assertContains(response, "&lt;script&gt;provider&lt;/script&gt;")
        self.assertNotContains(response, "<script>")
        self.assertEqual(
            client.post(
                reverse("snapshot_delete", args=[saved.pk]), {"confirmed": "on"}
            ).status_code,
            403,
        )
        self.client.logout()
        for url in (
            self.url,
            detail,
            reverse("snapshot_list"),
            reverse("snapshot_delete", args=[saved.pk]),
        ):
            self.assertEqual(self.client.get(url).status_code, 302)
            self.assertEqual(self.client.post(url).status_code, 302)
        self.alice.is_active = False
        self.alice.save(update_fields=["is_active"])
        self.client.force_login(self.alice)
        self.assertEqual(self.client.post(self.url).status_code, 302)

    def test_429_preserves_inputs_and_selection_and_exposes_retry_after(self):
        with patch.object(market_data, "search_securities", side_effect=ProviderRateLimited(17)):
            response = self.post("find", initial(self.alice))
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["Retry-After"], "17")
        self.assertContains(response, "Synthetic snapshot", status_code=429)
        self.assertContains(response, "Retry unresolved searches", status_code=429)
        with patch.object(market_data, "security_details", side_effect=ProviderRateLimited(19)):
            response = self.post("verify", matched(self.alice), holding_0=SECURITY.id)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.context["form"]["holding_0"].value(), SECURITY.id)
        self.assertFalse(HoldingsSnapshot.objects.exists())


@skipUnless(connection.vendor != "postgresql", "SQLite fallback only")
class SnapshotUnavailableTests(TestCase):
    def test_private_persistence_is_explicitly_unavailable(self):
        user = get_user_model().objects.create_user("snapshot-unavailable")
        self.client.force_login(user)
        for url in (
            reverse("snapshot_list"),
            reverse("snapshot_detail", args=[uuid.uuid4()]),
            reverse("snapshot_delete", args=[uuid.uuid4()]),
        ):
            self.assertEqual(self.client.get(url).status_code, 503)
        self.assertEqual(self.client.post(reverse("snapshot_import")).status_code, 503)
        with self.assertRaises(PortfolioStorageUnavailable):
            services.save_snapshot(user=user, token="", confirmed=True)
