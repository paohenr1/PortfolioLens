"""Inline portfolio analysis keeps owner isolation and bounded, shared price loading."""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase
from django.urls import reverse

from ledger.models import Entry
from ledger.services import append_entry
from market_data.errors import ProviderRateLimited
from portfolios.services import create_portfolio
from tests.test_ledger import REFERENCE
from tests.test_ledger_domain import DAY, cash, trade
from tests.test_valuation import history

END = date(2020, 1, 8)


@skipUnless(connection.vendor == "postgresql", "Private overview requires PostgreSQL")
class PortfolioOverviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("overview-owner")
        cls.other = get_user_model().objects.create_user("overview-other")
        cls.portfolio = create_portfolio(owner=cls.user, name="Overview example")
        cls.foreign = create_portfolio(owner=cls.other, name="Foreign secret")

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse("portfolio_overview_load", args=[self.portfolio.pk])
        self.data = {"start_date": DAY, "end_date": END, "timing_checked": "on"}
        self.reference = patch(
            "ledger.services.market_data.security_details", return_value=REFERENCE
        ).start()
        self.quotes = patch("ledger.valuation_services.market_data.daily_prices").start()
        self.addCleanup(patch.stopall)

    def record(self, event):
        append_entry(
            user=self.user,
            portfolio_id=self.portfolio.pk,
            client_key=uuid.uuid4(),
            intent=event,
            client_address="127.0.0.1",
        )

    def test_opening_overview_shows_recorded_totals_without_provider_requests_or_writes(self):
        self.record(cash())
        self.record(trade())
        count = Entry.objects.count()
        self.reference.reset_mock()
        response = self.client.get(reverse("portfolio_detail", args=[self.portfolio.pk]))
        self.assertEqual(response.context["analysis"].cash, Decimal("749.00"))
        self.assertContains(response, "Valuation &amp; performance")
        self.assertContains(response, "749.00")
        self.quotes.assert_not_called()
        self.reference.assert_not_called()
        self.assertEqual(Entry.objects.count(), count)

    def test_combined_load_reuses_closing_prices_and_renders_results_inline(self):
        self.record(cash())
        self.record(trade())
        self.quotes.side_effect = lambda identifier, day, address: history(
            "25" if day == DAY else "30", as_of=day
        )
        response = self.client.post(self.url, self.data)
        self.assertEqual(response.status_code, 200)
        # 749 cash + 300 holdings; 49 unrealized gain; 50/999 * 100 return.
        self.assertEqual(response.context["valuation"].total_value, Decimal("1049.00"))
        self.assertEqual(response.context["valuation"].unrealized_gain, Decimal("49.00"))
        self.assertEqual(response.context["performance"].return_percent, Decimal("5.0050"))
        self.assertEqual(self.quotes.call_count, 2)
        self.assertContains(response, "5.0050%")
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_unsupported_intraday_flow_keeps_closing_value_without_invented_return(self):
        self.record(cash())
        self.record(trade())
        self.quotes.return_value = history("30", as_of=END)
        response = self.client.post(self.url, {**self.data, "start_date": DAY - timedelta(days=1)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["valuation"].total_value, Decimal("1049.00"))
        self.assertNotIn("performance", response.context)
        self.assertContains(response, "must follow all other")
        self.assertEqual(self.quotes.call_count, 1)

    def test_missing_close_withholds_totals_and_return_without_replacing_known_cash(self):
        self.record(cash())
        self.record(trade())
        self.quotes.side_effect = lambda identifier, day, address: history(
            None if day == END else "25", as_of=day
        )
        response = self.client.post(self.url, self.data)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["valuation"].total_value)
        self.assertIsNone(response.context["performance"].return_percent)
        self.assertEqual(response.context["valuation"].cash, Decimal("749.00"))
        self.assertContains(response, "Some holdings lack a confirmed closing price")
        self.assertEqual(self.quotes.call_count, 2)

    def test_cash_only_zero_return_needs_no_prices_and_zero_is_displayed(self):
        self.record(cash())
        response = self.client.post(self.url, self.data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "0.0000%")
        self.assertEqual(response.context["valuation"].total_value, Decimal("1000.00"))
        self.quotes.assert_not_called()

    def test_rate_limit_stops_remaining_boundaries_and_preserves_retry_header(self):
        self.record(cash())
        self.record(trade())
        self.quotes.side_effect = ProviderRateLimited(17)
        response = self.client.post(self.url, self.data)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["Retry-After"], "17")
        self.assertEqual(self.quotes.call_count, 1)
        self.assertIsNone(response.context["valuation"].total_value)

    def test_invalid_confirmation_csrf_and_foreign_portfolio_never_request_prices(self):
        response = self.client.post(self.url, {**self.data, "timing_checked": ""})
        self.assertEqual(response.status_code, 400)
        response = self.client.post(
            reverse("portfolio_overview_load", args=[self.foreign.pk]), self.data
        )
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, "Foreign secret", status_code=404)
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.user)
        self.assertEqual(protected.post(self.url, self.data).status_code, 403)
        self.quotes.assert_not_called()
        self.reference.assert_not_called()
