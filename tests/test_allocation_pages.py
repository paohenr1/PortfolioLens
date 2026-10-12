"""Weights reuse private PostgreSQL valuations without requests or writes of their own."""

import uuid
from dataclasses import replace
from decimal import Decimal
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.urls import reverse

from ledger.models import Entry
from ledger.services import append_entry
from market_data.errors import ProviderRateLimited
from portfolios.services import create_portfolio
from tests.test_ledger import REFERENCE
from tests.test_ledger_domain import cash, trade
from tests.test_valuation import AS_OF, history


@skipUnless(connection.vendor == "postgresql", "Private allocation requires PostgreSQL")
class AllocationPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user("allocation-owner")
        cls.other = get_user_model().objects.create_user("allocation-other")
        cls.portfolio = create_portfolio(owner=cls.owner, name="Allocation example")
        cls.foreign = create_portfolio(owner=cls.other, name="Secret allocation")

    def setUp(self):
        self.client.force_login(self.owner)
        self.reference = patch(
            "ledger.services.market_data.security_details", return_value=REFERENCE
        ).start()
        self.quotes = patch(
            "ledger.valuation_services.market_data.daily_prices", return_value=history()
        ).start()
        self.addCleanup(patch.stopall)

    def record(self, intent):
        return append_entry(
            user=self.owner,
            portfolio_id=self.portfolio.pk,
            client_key=uuid.uuid4(),
            intent=intent,
            client_address="127.0.0.1",
        )

    def load(self):
        return self.client.post(
            reverse("portfolio_valuation", args=[self.portfolio.pk]),
            {"as_of": AS_OF.isoformat(), "share_basis_checked": "on"},
        )

    def test_get_never_claims_weights_or_fetches_prices(self):
        response = self.client.get(reverse("portfolio_valuation", args=[self.portfolio.pk]))
        self.assertNotContains(response, "Allocation weights ·")
        self.assertNotIn("allocation", response.context)
        self.quotes.assert_not_called()

    def test_post_includes_cash_and_no_extra_calls_or_journal_writes(self):
        self.record(cash())
        self.record(trade())
        before = list(Entry.objects.values())
        response = self.load()
        self.assertContains(response, "82.85%")
        self.assertContains(response, "17.15%")
        self.assertContains(response, "Total value (USD): 904.00")
        self.assertContains(response, "Recorded cash")
        self.assertEqual(self.quotes.call_count, 1)
        self.assertEqual(list(Entry.objects.values()), before)
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_cash_only_portfolio_has_one_hundred_percent_with_no_requests(self):
        self.record(cash())
        response = self.load()
        self.assertContains(response, "100.00%")
        self.assertIsNone(response.context["allocation"].issue)
        self.quotes.assert_not_called()

    def test_empty_portfolio_explains_zero_denominator_without_percentage(self):
        response = self.load()
        self.assertContains(response, "because total value is zero")
        self.assertNotContains(response, "100.00%")
        self.assertNotContains(response, "0.00%")
        self.assertTrue(all(row.weight is None for row in response.context["allocation"].rows))
        self.quotes.assert_not_called()

    def test_partial_prices_and_rate_limits_withhold_all_weights(self):
        self.record(cash())
        self.record(trade())
        self.quotes.return_value = replace(history(), observations=())
        response = self.load()
        self.assertContains(response, "until every position has a usable price")
        self.assertNotContains(response, "100.00%")
        self.assertTrue(all(row.weight is None for row in response.context["allocation"].rows))
        self.quotes.side_effect = ProviderRateLimited(120)
        response = self.load()
        self.assertContains(response, "until every position has a usable price", status_code=429)
        self.assertEqual(response.headers["Retry-After"], "120")
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_foreign_and_missing_portfolios_never_expose_components_or_prices(self):
        for identifier in (self.foreign.pk, uuid.uuid4()):
            response = self.client.post(
                reverse("portfolio_valuation", args=[identifier]),
                {"as_of": AS_OF.isoformat(), "share_basis_checked": "on"},
            )
            self.assertEqual(response.status_code, 404)
            self.assertNotContains(response, "Secret allocation", status_code=404)
            self.assertNotIn("allocation", response.context)
        self.quotes.assert_not_called()

    def test_three_equal_components_have_exact_reconciled_percentages(self):
        self.record(cash(amount="3"))
        for index in range(2):
            identifier = f"sec_fixture_{index}"
            self.reference.return_value = replace(
                REFERENCE, security=replace(REFERENCE.security, id=identifier)
            )
            self.record(
                trade(quantity="1", price="1", fees="0", sequence=index + 2, security_id=identifier)
            )
        self.quotes.side_effect = lambda identifier, *_: history("1", identifier=identifier)
        response = self.load()
        self.assertEqual(
            [row.weight for row in response.context["allocation"].rows],
            [Decimal("33.34"), Decimal("33.33"), Decimal("33.33")],
        )
        self.assertContains(response, "33.34%", count=1)
        self.assertContains(response, "33.33%", count=2)
        self.assertEqual(self.quotes.call_count, 2)
