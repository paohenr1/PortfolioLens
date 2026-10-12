"""Private bookmark boundaries and races run against actual PostgreSQL."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

import httpx
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.models.deletion import ProtectedError
from django.test import Client, SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from market_data.contracts import Security, SecurityResult
from market_data.errors import (
    CredentialsMissing,
    EntitlementDenied,
    InstrumentNotFound,
    InvalidResponse,
    ProviderError,
    ProviderRateLimited,
)
from market_data.intrinio import IntrinioClient
from research.services import _request_budget
from tests.test_intrinio import TEST_KEY, fixture
from watchlists import services
from watchlists.forms import InstrumentForm, WatchlistForm
from watchlists.models import Watchlist, WatchlistItem

REFERENCE = SecurityResult(
    Security("sec_fixture_primary", "TSTF", "Fixture Research Corp", "XNYS", "USD"),
    datetime(2020, 1, 2, tzinfo=UTC),
)


class WatchlistFormTests(SimpleTestCase):
    def test_name_bounds_control_characters_and_whitespace(self):
        for value in ("", "   ", "x" * 101, "Bad\nname", "Bad\x7fname"):
            with self.subTest(value=value):
                self.assertFalse(WatchlistForm({"name": value}).is_valid())
        form = WatchlistForm({"name": "  My research  "})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["name"], "My research")

    def test_identifiers_are_bounded_opaque_values(self):
        for value in ("", "x" * 101, "../../stocks", "sec/?key=value", "sec\n1", "sec 1"):
            with self.subTest(value=value):
                self.assertFalse(InstrumentForm({"security_id": value}).is_valid())
        self.assertTrue(InstrumentForm({"security_id": " sec_fixture_primary "}).is_valid())


@skipUnless(connection.vendor == "postgresql", "Watchlist persistence requires PostgreSQL")
class WatchlistTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = get_user_model().objects.create_user("watchlist-alice")
        cls.bob = get_user_model().objects.create_user("watchlist-bob")
        cls.own = services.create_watchlist(user=cls.alice, name="Alice research")
        cls.foreign = services.create_watchlist(user=cls.bob, name="Bob secret research")

    def setUp(self):
        self.client.force_login(self.alice)
        self.provider_patch = patch(
            "watchlists.services.market_data.security_details", return_value=REFERENCE
        )
        self.provider = self.provider_patch.start()
        self.addCleanup(patch.stopall)

    def url(self, name="watchlist_detail", watchlist=None, item=None):
        args = [(watchlist or self.own).pk]
        if item:
            args.append(item.pk)
        return reverse(name, args=args)

    def add(self, watchlist=None, user=None, identifier=REFERENCE.security.id):
        return services.add_instrument(
            user=user or self.alice,
            watchlist_id=(watchlist or self.own).pk,
            security_id=identifier,
            client_address="127.0.0.1",
        )

    def fill(self, watchlist=None, count=100):
        return WatchlistItem.objects.bulk_create(
            [
                WatchlistItem(
                    watchlist=watchlist or self.own,
                    security_id=f"sec_fixture_{n}",
                    reference_retrieved_at=REFERENCE.retrieved_at,
                )
                for n in range(count)
            ]
        )

    def test_create_uses_session_owner_and_trimmed_name(self):
        response = self.client.post(
            reverse("watchlist_create"),
            {
                "name": "  Income research  ",
                "owner": self.bob.pk,
            },
        )
        self.assertEqual(response.status_code, 302)
        created = Watchlist.objects.get(name="Income research")
        self.assertEqual(created.owner, self.alice)
        self.assertRedirects(response, self.url(watchlist=created))
        self.provider.assert_not_called()

    def test_name_uniqueness_is_case_insensitive_and_scoped_to_owner(self):
        response = self.client.post(reverse("watchlist_create"), {"name": " ALICE Research "})
        self.assertContains(
            response, "You already have a watchlist with this name.", status_code=400
        )
        services.create_watchlist(user=self.bob, name="Alice research")
        self.assertEqual(Watchlist.objects.count(), 3)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Watchlist.objects.create(owner=self.alice, name=" alice research ")

    def test_database_rejects_blank_name_or_missing_owner(self):
        for data in ({"name": " \t "}, {"owner_id": 999999}):
            with self.subTest(data=data), self.assertRaises(IntegrityError), transaction.atomic():
                Watchlist.objects.create(**{"name": "Fixture", "owner_id": self.alice.pk, **data})
                connection.check_constraints()

    def test_owner_deletion_does_not_silently_remove_watchlists(self):
        with self.assertRaises(ProtectedError):
            self.alice.delete()
        self.assertTrue(Watchlist.objects.filter(pk=self.own.pk).exists())

    def test_owner_limit_is_checked_before_creating(self):
        Watchlist.objects.bulk_create(
            [Watchlist(owner=self.alice, name=f"Fixture list {n}") for n in range(49)]
        )
        response = self.client.post(reverse("watchlist_create"), {"name": "Over allowance"})
        self.assertContains(response, "up to 50 watchlists", status_code=400)
        self.assertEqual(services.owned_watchlists(self.alice).count(), 50)
        self.assertEqual(services.create_watchlist(user=self.bob, name="Allowed").owner, self.bob)

    def test_listing_paginates_only_owned_watchlists(self):
        Watchlist.objects.bulk_create(
            [Watchlist(owner=self.alice, name=f"Fixture list {n}") for n in range(24)]
        )
        first = self.client.get(reverse("watchlist_list"), {"owner": self.bob.pk})
        second = self.client.get(reverse("watchlist_list"), {"page": 2})
        self.assertEqual(len(first.context["page"]), 20)
        self.assertEqual(len(second.context["page"]), 5)
        self.assertNotContains(first, self.foreign.name)
        self.assertNotContains(second, self.foreign.name)
        self.provider.assert_not_called()

    def test_add_stores_verified_reference_and_no_price_fields(self):
        response = self.client.post(
            self.url("watchlist_add"), {"security_id": REFERENCE.security.id}
        )
        self.assertRedirects(response, self.url())
        item = self.own.items.get()
        self.assertEqual(
            (item.security_id, item.ticker, item.name, item.exchange_mic, item.currency),
            ("sec_fixture_primary", "TSTF", "Fixture Research Corp", "XNYS", "USD"),
        )
        self.assertEqual(item.reference_retrieved_at, REFERENCE.retrieved_at)
        self.provider.assert_called_once_with("sec_fixture_primary", "127.0.0.1")

    def test_duplicate_add_keeps_original_snapshot_and_uses_no_request(self):
        item = self.add()
        self.provider.reset_mock()
        self.provider.side_effect = AssertionError("A retry must not call Intrinio")
        self.assertEqual(self.add().pk, item.pk)
        self.assertEqual(self.own.items.count(), 1)
        self.assertEqual(self.own.items.get().reference_retrieved_at, REFERENCE.retrieved_at)
        self.provider.assert_not_called()

    def test_same_instrument_can_be_on_different_lists(self):
        own_item = self.add()
        foreign_item = self.add(watchlist=self.foreign, user=self.bob)
        self.assertNotEqual(own_item.pk, foreign_item.pk)
        self.assertEqual(WatchlistItem.objects.count(), 2)

    def test_unknown_reference_fields_remain_unknown(self):
        self.provider.return_value = replace(
            REFERENCE, security=Security(REFERENCE.security.id, None, None, None, None)
        )
        self.add()
        response = self.client.get(self.url())
        for message in (
            "Ticker unavailable",
            "Name unavailable",
            "MIC unavailable",
            "Currency unavailable",
            "Status unavailable",
        ):
            self.assertContains(response, message)
        self.assertNotContains(response, "USD")

    def test_non_usd_reference_is_a_bookmark_without_a_currency_total(self):
        self.provider.return_value = replace(
            REFERENCE,
            security=replace(
                REFERENCE.security,
                currency="CAD",
                exchange_mic="XTSE",
                active=False,
                delisted=True,
            ),
        )
        self.add()
        response = self.client.get(self.url())
        self.assertContains(response, "XTSE · CAD")
        self.assertContains(response, "Delisted")
        self.assertNotContains(response, "Market value")

    def test_wrong_id_naive_timestamp_and_invalid_metadata_are_not_saved(self):
        for result in (
            replace(REFERENCE, security=replace(REFERENCE.security, id="sec_wrong")),
            replace(REFERENCE, retrieved_at=datetime(2020, 1, 2)),
            replace(REFERENCE, security=replace(REFERENCE.security, ticker="x" * 33)),
            replace(REFERENCE, security=replace(REFERENCE.security, name="Unsafe\nname")),
            replace(REFERENCE, security=replace(REFERENCE.security, active="yes")),
        ):
            with self.subTest(result=result):
                self.provider.return_value = result
                with self.assertRaises(InvalidResponse):
                    self.add()
                self.assertEqual(WatchlistItem.objects.count(), 0)

    def test_unexpected_provider_exception_is_safe_in_response_and_logs(self):
        secret = "fixture-secret-query-value"
        self.provider.side_effect = RuntimeError(f"https://example.invalid/?api_key={secret}")
        with self.assertLogs("research", level="ERROR") as logs:
            response = self.client.post(
                self.url("watchlist_add"), {"security_id": REFERENCE.security.id}
            )
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(secret, response.content.decode())
        self.assertNotIn(secret, " ".join(logs.output))
        self.assertEqual(WatchlistItem.objects.count(), 0)

    def test_provider_failures_keep_form_and_preserve_existing_items(self):
        self.fill(count=1)
        for error in (
            CredentialsMissing(),
            EntitlementDenied(),
            InstrumentNotFound(),
            ProviderRateLimited(42),
            InvalidResponse(),
            ProviderError(),
        ):
            with self.subTest(error=error):
                self.provider.side_effect = error
                response = self.client.post(
                    self.url("watchlist_add"),
                    {
                        "security_id": REFERENCE.security.id,
                    },
                )
                self.assertContains(response, error.message, status_code=error.status)
                self.assertIn("no-store", response.headers["Cache-Control"])
                self.assertEqual(WatchlistItem.objects.count(), 1)
                if error.retry_after:
                    self.assertEqual(response.headers["Retry-After"], "42")

    def test_item_limit_and_existing_retry_are_checked_before_provider(self):
        items = self.fill()
        with self.assertRaisesMessage(ValidationError, "up to 100 instruments"):
            self.add()
        self.assertEqual(self.add(identifier=items[0].security_id).pk, items[0].pk)
        self.provider.assert_not_called()

    def test_invalid_id_is_rejected_before_provider_and_writes(self):
        for identifier in ("../../invalid", "x" * 101, ""):
            with self.assertRaises(ValidationError):
                self.add(identifier=identifier)
            response = self.client.post(self.url("watchlist_add"), {"security_id": identifier})
            self.assertEqual(response.status_code, 400)
        self.provider.assert_not_called()
        self.assertEqual(WatchlistItem.objects.count(), 0)

    def test_choose_form_contains_only_own_lists_and_rejects_foreign_selection(self):
        url = reverse("watchlist_choose")
        response = self.client.get(url, {"security_id": REFERENCE.security.id})
        self.assertContains(response, self.own.name)
        self.assertNotContains(response, self.foreign.name)
        self.assertEqual(response.context["form"].initial["security_id"], REFERENCE.security.id)
        response = self.client.post(
            url, {"watchlist": self.foreign.pk, "security_id": REFERENCE.security.id}
        )
        self.assertEqual(response.status_code, 400)
        self.provider.assert_not_called()
        response = self.client.post(
            url, {"watchlist": self.own.pk, "security_id": REFERENCE.security.id}
        )
        self.assertRedirects(response, self.url())
        self.assertEqual(self.own.items.count(), 1)

    def test_signed_out_routes_redirect_before_queries_or_provider(self):
        self.client.logout()
        for url in (
            reverse("watchlist_list"),
            reverse("watchlist_create"),
            reverse("watchlist_choose"),
            self.url(),
            self.url("watchlist_add"),
            reverse("watchlist_remove", args=[self.own.pk, uuid.uuid4()]),
        ):
            for method in (self.client.get, self.client.post):
                response = method(url)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.url.startswith(reverse("sign_in") + "?next="))
                self.assertIn("no-store", response.headers["Cache-Control"])
        self.provider.assert_not_called()

    def test_foreign_or_missing_lists_have_same_generic_error_before_provider(self):
        for watchlist_id in (self.foreign.pk, uuid.uuid4()):
            for name in ("watchlist_detail", "watchlist_add"):
                url = reverse(name, args=[watchlist_id])
                for method in (self.client.get, self.client.post):
                    response = method(url, {"security_id": REFERENCE.security.id})
                    # Detail is intentionally read-only, even for the owner.
                    self.assertEqual(
                        response.status_code,
                        405 if name == "watchlist_detail" and method == self.client.post else 404,
                    )
                    self.assertNotContains(
                        response, self.foreign.name, status_code=response.status_code
                    )
                    self.assertIn("no-store", response.headers["Cache-Control"])
        self.provider.assert_not_called()

    def test_owner_check_is_repeated_after_lookup(self):
        def deactivate(*args):
            get_user_model().objects.filter(pk=self.alice.pk).update(is_active=False)
            return REFERENCE

        self.provider.side_effect = deactivate
        with self.assertRaises(services.WatchlistUnavailable):
            self.add()
        self.assertEqual(WatchlistItem.objects.count(), 0)

    def test_anonymous_or_inactive_service_call_is_denied(self):
        inactive = get_user_model().objects.create_user("inactive-watchlist", is_active=False)
        for user in (AnonymousUser(), inactive):
            with self.assertRaises(PermissionDenied):
                services.owned_watchlists(user)
            with self.assertRaises(PermissionDenied):
                services.create_watchlist(user=user, name="Forbidden")
        self.provider.assert_not_called()

    def test_detail_pagination_escaping_and_reference_provenance(self):
        self.fill(count=30)
        Watchlist.objects.filter(pk=self.own.pk).update(name="<script>unsafe fixture</script>")
        first = self.client.get(self.url())
        second = self.client.get(self.url(), {"page": 2})
        self.assertEqual(len(first.context["page"]), 25)
        self.assertEqual(len(second.context["page"]), 5)
        self.assertContains(first, "&lt;script&gt;unsafe fixture&lt;/script&gt;")
        self.assertNotContains(first, "<script>unsafe fixture</script>")
        self.assertContains(first, "2020-01-02 00:00:00 UTC")
        self.provider.assert_not_called()

    def test_read_pages_and_remove_confirmation_make_no_provider_calls_or_writes(self):
        item = self.add()
        self.provider.reset_mock()
        for url in (
            reverse("watchlist_list"),
            reverse("watchlist_create"),
            reverse("watchlist_choose"),
            self.url(),
            self.url("watchlist_add"),
            self.url("watchlist_remove", item=item),
        ):
            self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.own.items.count(), 1)
        self.provider.assert_not_called()

    def test_remove_is_scoped_and_does_not_call_provider(self):
        item = self.add()
        foreign_item = self.add(watchlist=self.foreign, user=self.bob)
        self.provider.reset_mock()
        for watchlist, target in ((self.foreign, foreign_item), (self.own, foreign_item)):
            for method in (self.client.get, self.client.post):
                response = method(self.url("watchlist_remove", watchlist, target))
                self.assertEqual(response.status_code, 404)
                self.assertIn("no-store", response.headers["Cache-Control"])
        response = self.client.post(self.url("watchlist_remove", item=item))
        self.assertRedirects(response, self.url())
        self.assertFalse(WatchlistItem.objects.filter(pk=item.pk).exists())
        self.assertTrue(WatchlistItem.objects.filter(pk=foreign_item.pk).exists())
        self.assertEqual(self.client.post(self.url("watchlist_remove", item=item)).status_code, 404)
        self.provider.assert_not_called()

    def test_create_add_and_remove_require_real_csrf_tokens(self):
        item = self.add()
        self.provider.reset_mock()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.alice)
        for url, data in (
            (reverse("watchlist_create"), {"name": "Forbidden create"}),
            (self.url("watchlist_add"), {"security_id": "sec_fixture_other"}),
            (self.url("watchlist_remove", item=item), {}),
        ):
            response = client.post(url, data)
            self.assertEqual(response.status_code, 403)
            self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(Watchlist.objects.count(), 2)
        self.assertEqual(WatchlistItem.objects.count(), 1)
        client.get(self.url("watchlist_remove", item=item))
        response = client.post(
            self.url("watchlist_remove", item=item),
            {
                "csrfmiddlewaretoken": client.cookies["csrftoken"].value,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(WatchlistItem.objects.count(), 0)
        self.provider.assert_not_called()

    def test_disallowed_methods_and_route_errors_are_private(self):
        for url in (
            reverse("watchlist_list"),
            self.url(),
            self.url("watchlist_add"),
            reverse("watchlist_create"),
            reverse("watchlist_choose"),
        ):
            response = self.client.put(url)
            self.assertEqual(response.status_code, 405)
            self.assertIn("no-store", response.headers["Cache-Control"])
        response = self.client.get("/watchlists/not-a-uuid/")
        self.assertEqual(response.status_code, 404)
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_database_enforces_instrument_identity_and_uniqueness(self):
        item = self.add()
        for identifier in (item.security_id, "", "sec/bad"):
            with (
                self.subTest(identifier=identifier),
                self.assertRaises(IntegrityError),
                transaction.atomic(),
            ):
                WatchlistItem.objects.create(
                    watchlist=self.own,
                    security_id=identifier,
                    reference_retrieved_at=REFERENCE.retrieved_at,
                )

    @override_settings(INTRINIO_API_KEY=TEST_KEY)
    def test_actual_adapter_uses_shared_budget_and_never_fetches_prices(self):
        self.provider_patch.stop()
        _request_budget.reset()
        self.addCleanup(_request_budget.reset)
        requests = []

        def transport(request):
            requests.append(request.url.path)
            return httpx.Response(200, json=fixture("security_reference.json"))

        with patch(
            "research.services.IntrinioClient",
            side_effect=lambda key: IntrinioClient(
                key,
                transport=httpx.MockTransport(transport),
            ),
        ):
            item = self.add()
            self.add()
            self.client.get(self.url())
            services.remove_instrument(user=self.alice, watchlist_id=self.own.pk, item_id=item.pk)
            self.assertEqual(requests, ["/securities/sec_fixture_primary"])
            self.assertEqual(_request_budget._total, 1)
            # Exhausting the shared research allowance blocks a new bookmark too.
            for _ in range(9):
                _request_budget.reserve("127.0.0.1")
            response = self.client.post(
                self.url("watchlist_add"), {"security_id": REFERENCE.security.id}
            )
            self.assertEqual(response.status_code, 429)
            self.assertIn("Retry-After", response.headers)
            self.assertEqual(WatchlistItem.objects.count(), 0)
            self.assertEqual(len(requests), 1)

    def test_removed_instrument_can_be_added_again_with_new_reference(self):
        item = self.add()
        services.remove_instrument(user=self.alice, watchlist_id=self.own.pk, item_id=item.pk)
        refreshed = replace(REFERENCE, retrieved_at=datetime(2020, 2, 1, tzinfo=UTC))
        self.provider.return_value = refreshed
        recreated = self.add()
        self.assertNotEqual(recreated.pk, item.pk)
        self.assertEqual(recreated.reference_retrieved_at, refreshed.retrieved_at)
        self.assertEqual(self.provider.call_count, 2)


@skipUnless(connection.vendor == "postgresql", "Concurrency requires real PostgreSQL")
class WatchlistConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("watchlist-race-owner")
        self.watchlist = services.create_watchlist(user=self.owner, name="Race fixture")

    def race(self, action):
        barrier = Barrier(2)

        def worker(index):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return action(index)
            except ValidationError:
                return None
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(worker, (0, 1)))

    def test_concurrent_duplicate_names_create_only_one_list(self):
        results = self.race(
            lambda index: services.create_watchlist(
                user=self.owner,
                name=("Same list", " SAME LIST ")[index],
            )
        )
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(Watchlist.objects.count(), 2)

    def test_concurrent_creations_cannot_exceed_owner_limit(self):
        Watchlist.objects.bulk_create(
            [Watchlist(owner=self.owner, name=f"Fixture list {n}") for n in range(48)]
        )
        results = self.race(
            lambda index: services.create_watchlist(
                user=self.owner,
                name=f"Last place {index}",
            )
        )
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(Watchlist.objects.count(), 50)

    def add_race(self, identifiers):
        provider_barrier = Barrier(2)

        def reference(identifier, address):
            # Both requests finish preflight before either performs its locked write.
            provider_barrier.wait(timeout=10)
            return replace(REFERENCE, security=replace(REFERENCE.security, id=identifier))

        with patch("watchlists.services.market_data.security_details", side_effect=reference):
            return self.race(
                lambda index: services.add_instrument(
                    user=self.owner,
                    watchlist_id=self.watchlist.pk,
                    security_id=identifiers[index],
                    client_address="127.0.0.1",
                )
            )

    def test_concurrent_duplicate_adds_create_one_item(self):
        results = self.add_race((REFERENCE.security.id, REFERENCE.security.id))
        self.assertEqual(results[0].pk, results[1].pk)
        self.assertEqual(WatchlistItem.objects.count(), 1)

    def test_concurrent_additions_cannot_exceed_item_limit(self):
        WatchlistItem.objects.bulk_create(
            [
                WatchlistItem(
                    watchlist=self.watchlist,
                    security_id=f"sec_fixture_{n}",
                    reference_retrieved_at=REFERENCE.retrieved_at,
                )
                for n in range(99)
            ]
        )
        results = self.add_race(("sec_fixture_extra_a", "sec_fixture_extra_b"))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(WatchlistItem.objects.count(), 100)


class WatchlistStorageGuardTests(TestCase):
    def test_unconfigured_storage_returns_503_before_lookup_or_mutation(self):
        user = get_user_model().objects.create_user("watchlist-storage-fixture")
        self.client.force_login(user)
        with (
            patch("watchlists.services.connection") as database,
            patch(
                "watchlists.services.market_data.security_details",
                side_effect=AssertionError,
            ) as provider,
        ):
            database.vendor = "sqlite"
            for url in (
                reverse("watchlist_list"),
                reverse("watchlist_create"),
                reverse("watchlist_choose"),
                reverse("watchlist_detail", args=[uuid.uuid4()]),
                reverse("watchlist_add", args=[uuid.uuid4()]),
                reverse("watchlist_remove", args=[uuid.uuid4(), uuid.uuid4()]),
            ):
                response = self.client.get(url)
                self.assertContains(
                    response, "Watchlist storage is not configured", status_code=503
                )
                self.assertIn("no-store", response.headers["Cache-Control"])
                if "/items/" in url or url.endswith(("/create/", "/add/")):
                    self.assertEqual(self.client.post(url, {}).status_code, 503)
            with self.assertRaises(services.WatchlistStorageUnavailable):
                services.create_watchlist(user=user, name="Not saved")
            provider.assert_not_called()
        self.assertEqual(Watchlist.objects.count(), 0)
        self.assertEqual(WatchlistItem.objects.count(), 0)
