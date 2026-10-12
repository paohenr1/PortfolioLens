"""Private as-of valuations on actual PostgreSQL, with synthetic provider transport."""

import uuid
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from unittest import skipUnless
from unittest.mock import patch

import httpx
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from ledger.analytics import positions_snapshot
from ledger.domain import EventInput, LedgerRuleError
from ledger.forms import ledger_today
from ledger.models import Entry
from ledger.services import append_entry
from market_data.errors import CredentialsMissing, ProviderRateLimited
from market_data.intrinio import IntrinioClient
from portfolios.services import create_portfolio
from research.services import _request_budget
from research.services import daily_prices as actual_daily_prices
from tests.test_intrinio import TEST_KEY
from tests.test_ledger import REFERENCE
from tests.test_ledger_domain import cash, trade
from tests.test_prices import observation, payload
from tests.test_valuation import AS_OF, IDENTIFIER, history

D = Decimal


@skipUnless(connection.vendor == "postgresql", "Private valuation requires PostgreSQL")
class ValuationPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = get_user_model().objects.create_user("valuation-alice")
        cls.bob = get_user_model().objects.create_user("valuation-bob")
        cls.portfolio = create_portfolio(owner=cls.alice, name="Valuation example")
        cls.foreign = create_portfolio(owner=cls.bob, name="Secret foreign valuation")

    def setUp(self):
        self.client.force_login(self.alice)
        self.reference = patch(
            "ledger.services.market_data.security_details", return_value=REFERENCE
        ).start()
        self.quotes = patch(
            "ledger.valuation_services.market_data.daily_prices", return_value=history()
        ).start()
        _request_budget.reset()
        self.addCleanup(_request_budget.reset)
        self.addCleanup(patch.stopall)

    def record(self, intent):
        return append_entry(
            user=self.alice,
            portfolio_id=self.portfolio.pk,
            client_key=uuid.uuid4(),
            intent=intent,
            client_address="127.0.0.1",
        )

    def url(self, portfolio=None):
        return reverse("portfolio_valuation", args=[(portfolio or self.portfolio).pk])

    def load(self, **data):
        return self.client.post(
            self.url(), {"as_of": AS_OF.isoformat(), "share_basis_checked": "on", **data}
        )

    def test_get_has_form_no_quotes_and_no_claimed_values(self):
        self.record(cash())
        response = self.client.get(self.url(), {"as_of": AS_OF.isoformat(), "load": "1"})
        self.assertContains(response, "Load valuation")
        self.assertNotIn("valuation", response.context)
        self.quotes.assert_not_called()
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_post_real_values_and_repeat_load_never_change_journal(self):
        self.record(cash())
        self.record(trade())
        before = list(Entry.objects.values())
        for _ in range(2):
            response = self.load()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context["valuation"].total_value, D("904.00"))
            for text in (
                "155.00",
                "-96.00",
                "904.00",
                "USD/share",
                "2020-01-08",
                "Intrinio historical stock prices",
                "Retrieved",
                "raw close",
            ):
                self.assertContains(response, text)
            self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(list(Entry.objects.values()), before)
        self.assertEqual(self.quotes.call_count, 2)
        self.assertEqual(self.quotes.call_args.args, (IDENTIFIER, AS_OF, "127.0.0.1"))

    def test_later_deposit_sale_and_split_are_excluded_at_price_date(self):
        self.record(cash())
        self.record(trade())
        self.record(cash(amount="100", event_date=date(2020, 1, 9)))
        self.record(trade("SELL", "2", "30", "0", 2, date(2020, 1, 9)))
        self.record(EventInput("SPLIT", date(2020, 1, 9), 3, IDENTIFIER, split_new=2, split_old=1))
        with self.assertNumQueries(2):
            _, analysis, _ = positions_snapshot(self.alice, self.portfolio.pk, as_of=AS_OF)
        self.assertEqual(analysis.cash, D("749.00"))
        self.assertEqual(analysis.positions[0].quantity, D("10"))
        result = self.load().context["valuation"]
        self.assertEqual(result.total_value, D("904.00"))
        self.assertEqual(result.open_cost_basis, D("251.00"))

    def test_selected_date_includes_same_day_split_and_net_dividend(self):
        self.record(cash())
        self.record(trade())
        self.record(EventInput("SPLIT", AS_OF, 1, IDENTIFIER, split_new=2, split_old=1))
        self.record(EventInput("DIVIDEND", AS_OF, 2, IDENTIFIER, amount=D("7")))
        result = self.load().context["valuation"]
        self.assertEqual(result.total_value, D("1066.00"))
        self.assertEqual(result.unrealized_gain, D("59.00"))

    def test_empty_cash_only_and_fully_closed_holdings_need_no_quotes(self):
        self.assertEqual(self.load().context["valuation"].total_value, D("0.00"))
        self.record(cash())
        self.assertEqual(self.load().context["valuation"].total_value, D("1000.00"))
        self.record(trade())
        self.record(trade("SELL", "10", "30", "1", 3))
        self.assertEqual(self.load().context["valuation"].total_value, D("1048.00"))
        self.quotes.assert_not_called()

    def test_invalid_date_or_unchecked_basis_spends_no_requests(self):
        for data in (
            {"as_of": "1899-12-31"},
            {"as_of": "bad"},
            {"as_of": ledger_today().isoformat()},
            {"as_of": (ledger_today() + timedelta(days=1)).isoformat()},
            {"share_basis_checked": ""},
        ):
            with self.subTest(data=data):
                self.assertEqual(self.load(**data).status_code, 400)
        self.quotes.assert_not_called()

    def test_five_instrument_cap_precedes_every_quote_request(self):
        self.record(cash())
        for index in range(6):
            identifier = f"sec_fixture_{index}"
            self.reference.return_value = replace(
                REFERENCE, security=replace(REFERENCE.security, id=identifier)
            )
            self.record(trade(quantity="1", price="1", sequence=index + 2, security_id=identifier))
        response = self.load()
        self.assertContains(response, "at most five open instruments", status_code=400)
        self.quotes.assert_not_called()

    def test_five_instruments_each_load_once_and_displayed_values_reconcile(self):
        self.record(cash())
        for index in range(5):
            identifier = f"sec_fixture_{index}"
            self.reference.return_value = replace(
                REFERENCE, security=replace(REFERENCE.security, id=identifier)
            )
            self.record(trade(quantity="1", price="1", sequence=index + 2, security_id=identifier))
        self.quotes.side_effect = lambda identifier, *_: history(identifier=identifier)
        result = self.load().context["valuation"]
        self.assertEqual(self.quotes.call_count, 5)
        self.assertEqual(len({call.args[0] for call in self.quotes.call_args_list}), 5)
        self.assertEqual(result.market_value, D("77.50"))
        self.assertEqual(result.unrealized_gain, D("67.50"))
        self.assertEqual(result.total_value, D("1067.50"))

    def test_missing_exact_date_shows_unavailable_totals_without_fake_zero(self):
        self.record(cash())
        self.record(trade())
        self.quotes.return_value = replace(history(), observations=())
        response = self.load()
        self.assertContains(response, "Incomplete valuation")
        self.assertIsNone(response.context["valuation"].total_value)
        self.assertNotContains(response, "904.00")
        self.assertContains(response, "Unavailable")

    def test_provider_failures_have_safe_messages_unknown_totals_and_retry_header(self):
        self.record(cash())
        self.record(trade())
        for error, status in ((CredentialsMissing(), 503), (ProviderRateLimited(120), 429)):
            self.quotes.side_effect = error
            response = self.load()
            self.assertContains(response, error.message, status_code=status)
            self.assertIsNone(response.context["valuation"].total_value)
            self.assertIn("no-store", response.headers["Cache-Control"])
            if status == 429:
                self.assertEqual(response.headers["Retry-After"], "120")

    def test_rate_limit_stops_remaining_instruments_and_keeps_prior_known_row(self):
        self.record(cash())
        for index in range(3):
            identifier = f"sec_fixture_{index}"
            self.reference.return_value = replace(
                REFERENCE, security=replace(REFERENCE.security, id=identifier)
            )
            self.record(trade(quantity="1", price="1", sequence=index + 2, security_id=identifier))
        self.quotes.side_effect = [history(identifier="sec_fixture_0"), ProviderRateLimited()]
        response = self.load()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(self.quotes.call_count, 2)
        self.assertEqual(response.context["valuation"].rows[0].market_value, D("15.50"))
        self.assertIsNone(response.context["valuation"].market_value)

    def test_owner_and_missing_lookup_fail_before_quote_or_form_evaluation(self):
        for identifier in (self.foreign.pk, uuid.uuid4()):
            for method in (self.client.get, self.client.post):
                response = method(
                    reverse("portfolio_valuation", args=[identifier]),
                    {"as_of": "bad", "owner": self.bob.pk},
                )
                self.assertEqual(response.status_code, 404)
                self.assertNotContains(response, "Secret foreign valuation", status_code=404)
                self.assertIn("no-store", response.headers["Cache-Control"])
        self.quotes.assert_not_called()

    def test_signed_out_user_and_disallowed_method_never_spend_quota(self):
        self.assertEqual(self.client.put(self.url()).status_code, 405)
        self.assertEqual(self.client.head(self.url()).status_code, 405)
        self.client.logout()
        response = self.load()
        self.assertEqual(response.status_code, 302)
        self.assertIn("/sign-in/?next=", response.url)
        self.quotes.assert_not_called()

    def test_csrf_required_for_quote_submission(self):
        self.record(cash())
        self.record(trade())
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.alice)
        data = {"as_of": AS_OF.isoformat(), "share_basis_checked": "on"}
        response = client.post(self.url(), data)
        self.assertEqual(response.status_code, 403)
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.quotes.assert_not_called()
        client.get(self.url())
        response = client.post(
            self.url(), {**data, "csrfmiddlewaretoken": client.cookies["csrftoken"].value}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.quotes.call_count, 1)

    def test_bad_journal_fails_closed_before_any_quotes(self):
        with patch("ledger.analytics.analyze", side_effect=LedgerRuleError("Bad history")):
            response = self.load()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("valuation", response.context)
        self.quotes.assert_not_called()

    def test_unexpected_error_is_redacted_in_page_and_log(self):
        self.record(cash())
        self.record(trade())
        self.quotes.side_effect = RuntimeError(TEST_KEY)
        with self.assertLogs("research", level="ERROR") as logs:
            response = self.load()
        self.assertNotContains(response, TEST_KEY, status_code=503)
        self.assertNotIn(TEST_KEY, "\n".join(logs.output))

    def test_quote_loading_uses_one_materialized_snapshot_despite_later_append(self):
        self.record(cash())
        self.record(trade())

        def load(*args):
            self.record(cash(amount="100", event_date=AS_OF))
            return history()

        self.quotes.side_effect = load
        result = self.load().context["valuation"]
        self.assertEqual(result.cash, D("749.00"))
        self.assertEqual(result.total_value, D("904.00"))
        self.assertEqual(positions_snapshot(self.alice, self.portfolio.pk)[1].cash, D("849.00"))

    @override_settings(INTRINIO_API_KEY=TEST_KEY)
    def test_real_adapter_success_incomplete_cursor_and_safe_failures(self):
        self.record(cash())
        self.record(trade())
        # Leave the actual daily service unmocked while replacing only HTTP transport.
        self.quotes.side_effect = actual_daily_prices
        requests = []
        for status, cursor, expected in (
            (200, None, 200),
            (200, "more", 200),
            (403, None, 503),
            (401, None, 503),
            (404, None, 503),
            (429, None, 429),
            (500, None, 503),
        ):
            _request_budget.reset()

            def handler(request, status=status, cursor=cursor):
                requests.append(request)
                return httpx.Response(
                    status,
                    json=payload([observation(AS_OF)], cursor),
                    headers={"Retry-After": "120"},
                )

            with patch(
                "research.services.IntrinioClient",
                side_effect=lambda key: IntrinioClient(key, transport=httpx.MockTransport(handler)),
            ):
                response = self.load()
            self.assertEqual(response.status_code, expected)
            if cursor or status != 200:
                self.assertIsNone(response.context["valuation"].total_value)
            else:
                self.assertEqual(response.context["valuation"].market_value, D("100.00"))
            self.assertNotContains(response, TEST_KEY, status_code=expected)
        self.assertEqual(len(requests), 7)
