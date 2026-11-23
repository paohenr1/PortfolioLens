"""Inline portfolio analysis keeps owner isolation and bounded, shared price loading."""

import uuid
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase, override_settings
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
        self.assertContains(response, "Recent transactions")
        self.assertEqual([event.sequence for event in response.context["recent_entries"]], [2, 1])
        self.quotes.assert_not_called()
        self.reference.assert_not_called()
        self.assertEqual(Entry.objects.count(), count)

    @override_settings(PORTFOLIO_VALUATION_CACHE=True)
    def test_automatic_valuation_uses_previous_session_and_reuses_unchanged_value(self):
        self.record(cash())
        self.record(trade())
        overview = self.client.get(reverse("portfolio_detail", args=[self.portfolio.pk]))
        self.assertContains(overview, "data-automatic-valuation")
        self.quotes.assert_not_called()
        auto_url = reverse("portfolio_automatic_valuation", args=[self.portfolio.pk])
        self.quotes.side_effect = lambda identifier, day, address, **kwargs: history(
            "30", as_of=day
        )
        with patch("portfolios.automatic_valuation.ledger_today", return_value=date(2020, 1, 13)):
            result = self.client.post(auto_url)
            repeated = self.client.post(auto_url)
            self.record(cash(amount="50", sequence=3))
            changed = self.client.post(auto_url)
        self.assertContains(result, "1,049.00")
        self.assertContains(result, "Closing date Jan 10, 2020")
        self.assertIn("no-store", result.headers["Cache-Control"])
        self.assertContains(repeated, "1,049.00")
        self.assertContains(changed, "1,099.00")
        self.assertEqual(self.quotes.call_count, 2)
        self.assertTrue(
            all(call.args[1] == date(2020, 1, 10) for call in self.quotes.call_args_list)
        )

    def test_automatic_valuation_enforces_owner_post_and_csrf(self):
        url = reverse("portfolio_automatic_valuation", args=[self.portfolio.pk])
        foreign_url = reverse("portfolio_automatic_valuation", args=[self.foreign.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertNotContains(self.client.post(foreign_url), "Foreign secret", status_code=404)
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.user)
        self.assertEqual(protected.post(url).status_code, 403)
        self.quotes.assert_not_called()

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
        self.assertContains(response, "28.60%")
        self.assertContains(response, "71.40% of total value")
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
        self.assertIsNone(response.context["cash_weight"])
        self.assertIsNone(response.context["valued_rows"][0]["weight"])
        self.assertEqual(self.quotes.call_count, 2)

    def test_cash_only_zero_return_needs_no_prices_and_zero_is_displayed(self):
        self.record(cash())
        response = self.client.post(self.url, self.data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "0.0000%")
        self.assertContains(response, "100.00% of total value")
        self.assertEqual(response.context["valuation"].total_value, Decimal("1000.00"))
        self.quotes.assert_not_called()

    def test_empty_portfolio_explains_why_allocation_weights_are_unavailable(self):
        response = self.client.post(self.url, self.data)
        self.assertContains(
            response, "Allocation weights are unavailable because total value is zero"
        )
        self.assertIsNone(response.context["cash_weight"])
        self.quotes.assert_not_called()

    def test_valuation_limit_preserves_recorded_holdings_and_recent_transactions(self):
        self.record(cash())
        for number in range(6):
            security_id = f"sec_overview_{number}"
            self.reference.return_value = replace(
                REFERENCE, security=replace(REFERENCE.security, id=security_id)
            )
            self.record(trade(quantity="1", sequence=number + 2, security_id=security_id))
        automatic = self.client.post(
            reverse("portfolio_automatic_valuation", args=[self.portfolio.pk])
        )
        self.assertContains(automatic, "Open manual valuation")
        self.quotes.assert_not_called()
        response = self.client.post(self.url, self.data)
        self.assertContains(response, "Valuation supports at most five", status_code=400)
        self.assertContains(response, "First five holdings shown", status_code=400)
        self.assertEqual(response.context["position_count"], 6)
        self.assertEqual(
            [event.sequence for event in response.context["recent_entries"]], [7, 6, 5, 4, 3]
        )
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
