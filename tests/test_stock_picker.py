"""Owner-isolated picker endpoints reuse bounded provider search and journal holdings."""

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase
from django.urls import reverse

from ledger.models import Entry
from ledger.services import append_entry
from market_data.contracts import SearchResult
from market_data.errors import ProviderRateLimited
from portfolios.services import create_portfolio
from tests.test_ledger import REFERENCE
from tests.test_ledger_domain import DAY, cash, trade


@skipUnless(connection.vendor == "postgresql", "Private picker requires PostgreSQL")
class StockPickerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("picker-owner")
        cls.other = get_user_model().objects.create_user("picker-other")
        cls.portfolio = create_portfolio(owner=cls.user, name="Picker portfolio")
        cls.foreign = create_portfolio(owner=cls.other, name="Foreign secret")

    def setUp(self):
        self.client.force_login(self.user)
        self.search_url = reverse("ledger_instrument_search", args=[self.portfolio.pk])
        self.held_url = reverse("ledger_held_instruments", args=[self.portfolio.pk])
        self.search = patch("ledger.picker_views.market_data.search_securities").start()
        self.reference = patch(
            "ledger.services.market_data.security_details", return_value=REFERENCE
        ).start()
        self.addCleanup(patch.stopall)

    def record(self, intent):
        return append_entry(
            user=self.user,
            portfolio_id=self.portfolio.pk,
            intent=intent,
            client_key=uuid.uuid4(),
            client_address="127.0.0.1",
        )

    def test_search_returns_selectable_listings_and_never_records_or_fetches_references(self):
        security = REFERENCE.security
        self.search.return_value = SearchResult(
            (
                security,
                replace(security, currency="CAD"),
                replace(security, exchange_mic="UNKNOWN"),
                replace(security, ticker=None),
            ),
            datetime.now(UTC),
        )
        response = self.client.post(self.search_url, {"q": "Apple"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["results"],
            [
                {
                    "id": security.id,
                    "ticker": security.ticker,
                    "name": security.name,
                    "exchange": security.exchange_mic,
                    "currency": "USD",
                }
            ],
        )
        self.search.assert_called_once_with("Apple", "127.0.0.1")
        self.reference.assert_not_called()
        self.assertEqual(Entry.objects.count(), 0)
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_search_is_post_csrf_and_owner_protected_before_provider_io(self):
        self.assertEqual(self.client.get(self.search_url).status_code, 405)
        foreign = reverse("ledger_instrument_search", args=[self.foreign.pk])
        self.assertEqual(self.client.post(foreign, {"q": "AAPL"}).status_code, 404)
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.user)
        self.assertEqual(protected.post(self.search_url, {"q": "AAPL"}).status_code, 403)
        for query in ("", "x" * 101, "bad\x00query"):
            self.assertEqual(self.client.post(self.search_url, {"q": query}).status_code, 400)
        self.search.assert_not_called()

    def test_rate_limit_preserves_retry_header_and_safe_message(self):
        self.search.side_effect = ProviderRateLimited(17)
        response = self.client.post(self.search_url, {"q": "AAPL"})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["Retry-After"], "17")
        self.assertEqual(response.json()["retry_after"], 17)

    def test_holdings_use_selected_date_and_make_no_provider_requests(self):
        self.record(cash())
        self.record(trade())
        self.record(trade("SELL", "4", "30", "2", 3, event_date=DAY + timedelta(days=1)))
        self.reference.reset_mock()
        before = list(Entry.objects.values())
        old = self.client.post(self.held_url, {"as_of": DAY})
        latest = self.client.post(self.held_url, {"as_of": DAY + timedelta(days=1)})
        self.assertEqual(old.json()["results"][0]["quantity"], "10.000000")
        self.assertEqual(latest.json()["results"][0]["quantity"], "6.000000")
        self.assertEqual(old.json()["cash"], "749.00")
        self.assertEqual(latest.json()["cash"], "867.00")
        self.search.assert_not_called()
        self.reference.assert_not_called()
        self.assertEqual(list(Entry.objects.values()), before)

    def test_holdings_invalid_dates_foreign_and_signed_out_reveal_no_data(self):
        self.assertEqual(self.client.post(self.held_url, {"as_of": "2099-01-01"}).status_code, 400)
        foreign = reverse("ledger_held_instruments", args=[self.foreign.pk])
        self.assertEqual(self.client.post(foreign, {"as_of": DAY}).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.post(self.held_url, {"as_of": DAY}).status_code, 302)
        self.search.assert_not_called()
