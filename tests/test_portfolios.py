"""Private storage tests run on real PostgreSQL, including creation races."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from portfolios import services
from portfolios.models import Portfolio


@skipUnless(connection.vendor == "postgresql", "Private portfolios require PostgreSQL")
class PortfolioTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = get_user_model().objects.create_user("portfolio-alice")
        cls.bob = get_user_model().objects.create_user("portfolio-bob")
        cls.owned = services.create_portfolio(owner=cls.alice, name="Alice retirement")
        cls.other = services.create_portfolio(owner=cls.bob, name="Bob private savings")

    def setUp(self):
        self.client.force_login(self.alice)

    def create(self, **data):
        return self.client.post(
            reverse("portfolio_create"), {"name": "Long term", "reporting_currency": "USD", **data}
        )

    def test_all_private_routes_redirect_signed_out_users(self):
        self.client.logout()
        for url in (
            reverse("portfolio_list"),
            reverse("portfolio_create"),
            reverse("portfolio_detail", args=[self.owned.pk]),
        ):
            with self.subTest(url=url):
                self.assertRedirects(self.client.get(url), f"/sign-in/?next={url}")
        self.assertEqual(Portfolio.objects.count(), 2)

    def test_list_contains_only_owner_objects_and_private_cache_headers(self):
        response = self.client.get(
            reverse("portfolio_list"), {"owner": self.bob.pk, "user_id": self.bob.pk}
        )
        self.assertContains(response, "Alice retirement")
        self.assertNotContains(response, "Bob private savings")
        self.assertNotContains(response, str(self.other.pk))
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_create_persists_explicit_usd_and_ignores_owner_id_injection(self):
        response = self.create(name="  Long term  ", owner=self.bob.pk, id=self.other.pk)
        portfolio = Portfolio.objects.get(name="Long term", owner=self.alice)
        self.assertRedirects(response, reverse("portfolio_detail", args=[portfolio.pk]))
        self.assertIsInstance(portfolio.pk, uuid.UUID)
        self.assertNotEqual(portfolio.pk, self.other.pk)
        self.assertEqual(portfolio.reporting_currency, "USD")
        self.assertEqual(Portfolio.objects.filter(owner=self.bob).count(), 1)

    def test_create_get_does_not_write(self):
        response = self.client.get(reverse("portfolio_create"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Portfolio.objects.count(), 2)
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_invalid_name_currency_or_missing_choice_cannot_create(self):
        for data in (
            {"name": " "},
            {"name": "x" * 101},
            {"name": "bad\x01name"},
            {"reporting_currency": "EUR"},
            {"reporting_currency": ""},
        ):
            with self.subTest(data=data):
                response = self.create(**data)
                self.assertTrue(response.context["form"].errors)
                self.assertEqual(Portfolio.objects.count(), 2)

    def test_duplicate_trimmed_case_insensitive_name_has_safe_form_error(self):
        response = self.create(name=" ALICE RETIREMENT ")
        self.assertContains(response, "You already have a portfolio with this name.")
        self.assertEqual(Portfolio.objects.count(), 2)
        # An integrity failure must not leave the request transaction unusable.
        self.assertContains(self.client.get(reverse("portfolio_list")), "Alice retirement")

    def test_same_name_is_allowed_for_a_different_owner(self):
        portfolio = services.create_portfolio(owner=self.bob, name="Alice retirement")
        self.assertEqual(portfolio.owner, self.bob)

    def test_owner_can_view_detail_without_placeholder_valuation(self):
        response = self.client.get(reverse("portfolio_detail", args=[self.owned.pk]))
        self.assertContains(response, "Alice retirement")
        self.assertContains(response, "View time-weighted returns")
        self.assertContains(response, "View market valuation")
        self.assertContains(response, "View positions and gains")
        self.assertNotContains(response, "$0")
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_foreign_and_missing_ids_have_identical_not_found_status(self):
        for portfolio_id in (self.other.pk, uuid.uuid4()):
            response = self.client.get(reverse("portfolio_detail", args=[portfolio_id]))
            self.assertEqual(response.status_code, 404)
            self.assertNotContains(response, "Bob private savings", status_code=404)
            self.assertIn("no-store", response.headers["Cache-Control"])

    def test_invalid_identifier_is_not_a_lookup(self):
        response = self.client.get("/portfolios/not-a-uuid/")
        self.assertEqual(response.status_code, 404)
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_query_owner_cannot_change_detail_identity(self):
        response = self.client.get(
            reverse("portfolio_detail", args=[self.owned.pk]), {"owner": self.bob.pk}
        )
        self.assertEqual(response.context["portfolio"], self.owned)

    def test_list_and_detail_reject_post_without_mutation(self):
        for url in (reverse("portfolio_list"), reverse("portfolio_detail", args=[self.owned.pk])):
            self.assertEqual(self.client.post(url).status_code, 405)
        self.assertEqual(Portfolio.objects.count(), 2)

    def test_csrf_enforcement_blocks_create_and_accepts_real_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.alice)
        self.assertEqual(
            client.post(
                reverse("portfolio_create"), {"name": "Extra", "reporting_currency": "USD"}
            ).status_code,
            403,
        )
        self.assertEqual(Portfolio.objects.count(), 2)
        client.get(reverse("portfolio_create"))
        response = client.post(
            reverse("portfolio_create"),
            {
                "name": "Extra",
                "reporting_currency": "USD",
                "csrfmiddlewaretoken": client.cookies["csrftoken"].value,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Portfolio.objects.count(), 3)

    def test_name_is_escaped_in_list_and_detail(self):
        portfolio = services.create_portfolio(
            owner=self.alice, name='<script>alert("fixture")</script>'
        )
        for url in (reverse("portfolio_list"), reverse("portfolio_detail", args=[portfolio.pk])):
            response = self.client.get(url)
            self.assertNotContains(response, '<script>alert("fixture")</script>')
            self.assertContains(response, "&lt;script&gt;")

    def test_pagination_is_bounded_and_owner_scoped(self):
        Portfolio.objects.bulk_create(
            [Portfolio(owner=self.alice, name=f"Account {n}") for n in range(25)]
        )
        first = self.client.get(reverse("portfolio_list"))
        self.assertEqual(len(first.context["page"].object_list), 20)
        self.assertContains(first, "Next page")
        second = self.client.get(reverse("portfolio_list"), {"page": 2})
        self.assertEqual(len(second.context["page"].object_list), 6)
        self.assertNotContains(second, "Bob private savings")

    def test_service_rejects_anonymous_and_inactive_owners(self):
        self.bob.is_active = False
        self.bob.save(update_fields=["is_active"])
        for user in (AnonymousUser(), self.bob):
            with self.assertRaises(PermissionDenied):
                services.owned_portfolios(user)
            with self.assertRaises(PermissionDenied):
                services.create_portfolio(owner=user, name="Not allowed")

    def test_owner_allowance_is_enforced_without_affecting_other_users(self):
        Portfolio.objects.bulk_create(
            [Portfolio(owner=self.alice, name=f"Allowance {n}") for n in range(49)]
        )
        response = self.create()
        self.assertContains(response, "An account can have up to 50 portfolios.")
        self.assertEqual(Portfolio.objects.filter(owner=self.alice).count(), 50)
        services.create_portfolio(owner=self.bob, name="Still allowed")
        self.assertEqual(Portfolio.objects.filter(owner=self.bob).count(), 2)

    def test_database_rejects_non_usd_blank_names_or_orphan_owner(self):
        for values in ({"reporting_currency": "EUR"}, {"name": " \t "}, {"owner_id": 999999}):
            with self.subTest(values=values):
                defaults = {"name": "Raw fixture", "owner_id": self.alice.pk, **values}
                with self.assertRaises(IntegrityError), transaction.atomic():
                    Portfolio.objects.create(**defaults)
                    # Deferred foreign keys are checked explicitly within this savepoint.
                    connection.check_constraints()

    def test_database_enforces_trimmed_lower_name_uniqueness(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Portfolio.objects.create(owner=self.alice, name=" alice RETIREMENT ")

    def test_owner_deletion_cannot_silently_delete_portfolios(self):
        with self.assertRaises(ProtectedError):
            self.alice.delete()
        self.assertTrue(Portfolio.objects.filter(pk=self.owned.pk).exists())

    def test_portfolio_workflow_does_not_call_provider(self):
        with patch("research.services.IntrinioClient", side_effect=AssertionError):
            self.assertEqual(self.client.get(reverse("portfolio_list")).status_code, 200)
            self.assertEqual(self.create().status_code, 302)


@skipUnless(connection.vendor == "postgresql", "Concurrency requires real PostgreSQL")
class PortfolioConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("concurrent-owner")

    def race(self, names):
        barrier = Barrier(2)

        def create(name):
            close_old_connections()
            try:
                owner = get_user_model().objects.get(pk=self.owner.pk)
                barrier.wait(timeout=5)
                try:
                    services.create_portfolio(owner=owner, name=name)
                    return "created"
                except ValidationError:
                    return "rejected"
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            return list(executor.map(create, names))

    def test_same_owner_name_race_creates_one_portfolio(self):
        self.assertCountEqual(self.race(("Retirement", "RETIREMENT")), ("created", "rejected"))
        self.assertEqual(Portfolio.objects.count(), 1)

    def test_concurrent_creations_cannot_exceed_owner_allowance(self):
        Portfolio.objects.bulk_create(
            [Portfolio(owner=self.owner, name=f"Existing {n}") for n in range(49)]
        )
        self.assertCountEqual(self.race(("One", "Two")), ("created", "rejected"))
        self.assertEqual(Portfolio.objects.count(), 50)


class PortfolioStorageGuardTests(TestCase):
    def test_unconfigured_storage_returns_unavailable_without_writes(self):
        user = get_user_model().objects.create_user("storage-fixture")
        self.client.force_login(user)
        with patch("portfolios.services.connection") as database:
            database.vendor = "sqlite"
            for url in (
                reverse("portfolio_list"),
                reverse("portfolio_create"),
                reverse("portfolio_detail", args=[uuid.uuid4()]),
                reverse("ledger_history", args=[uuid.uuid4()]),
                reverse("ledger_create", args=[uuid.uuid4()]),
                reverse("portfolio_positions", args=[uuid.uuid4()]),
                reverse("portfolio_valuation", args=[uuid.uuid4()]),
                reverse("portfolio_performance", args=[uuid.uuid4()]),
            ):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 503)
                self.assertContains(
                    response, "Portfolio storage is not configured", status_code=503
                )
                self.assertIn("no-store", response.headers["Cache-Control"])
            self.assertEqual(
                self.client.post(
                    reverse("portfolio_create"), {"name": "Not saved", "reporting_currency": "USD"}
                ).status_code,
                503,
            )
            with self.assertRaises(services.PortfolioStorageUnavailable):
                services.create_portfolio(owner=user, name="Not saved")
            self.assertEqual(
                self.client.post(reverse("ledger_create", args=[uuid.uuid4()]), {}).status_code,
                503,
            )
        self.assertEqual(Portfolio.objects.count(), 0)
