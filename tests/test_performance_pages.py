"""Actual PostgreSQL snapshots and private performance HTTP boundaries."""

import uuid
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase
from django.urls import reverse

from ledger.domain import EventInput, LedgerRuleError
from ledger.forms import ledger_today
from ledger.models import Entry
from ledger.performance_services import load_performance
from ledger.services import append_entry
from market_data.errors import CredentialsMissing, ProviderRateLimited
from portfolios.services import create_portfolio
from tests.test_intrinio import TEST_KEY
from tests.test_ledger import REFERENCE
from tests.test_ledger_domain import DAY, cash, trade
from tests.test_valuation import IDENTIFIER, history

D = Decimal
MIDDLE = date(2020, 1, 6)
END = date(2020, 1, 8)


@skipUnless(connection.vendor == "postgresql", "Private returns require PostgreSQL")
class PerformancePageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user("performance-owner")
        cls.other = get_user_model().objects.create_user("performance-other")
        cls.portfolio = create_portfolio(owner=cls.owner, name="Performance fixture")
        cls.foreign = create_portfolio(owner=cls.other, name="Private return secret")

    def setUp(self):
        self.client.force_login(self.owner)
        self.reference = patch(
            "ledger.services.market_data.security_details", return_value=REFERENCE
        ).start()
        self.quotes = patch(
            "ledger.valuation_services.market_data.daily_prices",
            side_effect=lambda identifier, day, *_: history("10", identifier=identifier, as_of=day),
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

    def url(self, identifier=None):
        return reverse("portfolio_performance", args=[identifier or self.portfolio.pk])

    def load(self, **data):
        return self.client.post(
            self.url(),
            {
                "start_date": DAY.isoformat(),
                "end_date": END.isoformat(),
                "timing_checked": "on",
                **data,
            },
        )

    def invested(self):
        self.record(cash())
        self.record(trade(quantity="10", price="10", fees="0"))

    def test_get_and_query_flags_make_no_requests_or_claimed_returns(self):
        response = self.client.get(self.url(), {"start_date": DAY.isoformat(), "load": "1"})
        self.assertContains(response, "Load returns")
        self.assertNotIn("performance", response.context)
        self.quotes.assert_not_called()
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_price_gain_uses_cash_inclusive_values_and_does_not_write(self):
        self.invested()
        before = list(Entry.objects.values())
        self.quotes.side_effect = lambda identifier, day, *_: history(
            "10" if day == DAY else "12", as_of=day
        )
        response = self.load()
        self.assertContains(response, "2.0000%")
        self.assertEqual(response.context["performance"].return_percent, D("2.0000"))
        self.assertEqual(self.quotes.call_count, 2)
        self.assertEqual(list(Entry.objects.values()), before)
        self.assertContains(response, "raw daily closes")
        self.assertContains(response, "retrieved")

    def test_cash_only_deposit_and_withdrawal_are_zero_return_without_quotes(self):
        self.record(cash())
        self.record(cash(amount="500", event_date=MIDDLE))
        self.record(cash("WITHDRAWAL", "250", event_date=END))
        response = self.load()
        self.assertContains(response, "0.0000%")
        result = response.context["performance"]
        self.assertEqual([period.external_flow for period in result.periods], [D("500"), D("-250")])
        self.quotes.assert_not_called()

    def test_fee_and_dividend_remain_internal_performance_without_double_counting(self):
        self.record(cash())
        self.record(cash("FEE", "2", event_date=MIDDLE))
        self.record(EventInput("DIVIDEND", MIDDLE, 2, IDENTIFIER, amount=D("10")))
        response = self.load()
        self.assertEqual(response.context["performance"].return_percent, D("0.8000"))
        self.assertEqual(len(response.context["performance"].periods), 1)
        self.quotes.assert_not_called()

    def test_split_changes_quantity_not_wealth_with_consistent_raw_closes(self):
        self.invested()
        self.record(EventInput("SPLIT", MIDDLE, 1, IDENTIFIER, split_new=2, split_old=1))
        self.quotes.side_effect = lambda identifier, day, *_: history(
            "10" if day == DAY else "5", as_of=day
        )
        result = self.load().context["performance"]
        self.assertEqual(result.return_percent, D("0.0000"))

    def test_intraday_funding_is_rejected_before_prices(self):
        self.invested()
        self.record(cash(amount="100", event_date=MIDDLE))
        self.record(trade(quantity="1", price="10", fees="0", sequence=2, event_date=MIDDLE))
        response = self.load()
        self.assertContains(response, "end-of-day flows", status_code=400)
        self.quotes.assert_not_called()

    def test_invalid_dates_or_unconfirmed_timing_spend_no_requests(self):
        for data in (
            {"start_date": END.isoformat()},
            {"start_date": "bad"},
            {"start_date": "1899-01-01"},
            {"end_date": ledger_today().isoformat()},
            {"end_date": (DAY + timedelta(days=366)).isoformat()},
            {"timing_checked": ""},
        ):
            with self.subTest(data=data):
                self.assertEqual(self.load(**data).status_code, 400)
        self.quotes.assert_not_called()

    def test_price_request_preflight_rejects_large_plan_without_partial_fetching(self):
        self.record(cash())
        for index in range(5):
            identifier = f"sec_fixture_{index}"
            self.reference.return_value = replace(
                REFERENCE, security=replace(REFERENCE.security, id=identifier)
            )
            self.record(
                trade(quantity="1", price="1", fees="0", sequence=index + 2, security_id=identifier)
            )
        self.assertContains(self.load(), "eight price requests", status_code=400)
        self.quotes.assert_not_called()

    def test_eight_required_quotes_load_each_exact_date_and_id_once(self):
        self.record(cash())
        for index in range(4):
            identifier = f"sec_fixture_{index}"
            self.reference.return_value = replace(
                REFERENCE, security=replace(REFERENCE.security, id=identifier)
            )
            self.record(
                trade(
                    quantity="1", price="10", fees="0", sequence=index + 2, security_id=identifier
                )
            )
        result = self.load().context["performance"]
        self.assertEqual(result.return_percent, D("0.0000"))
        self.assertEqual(self.quotes.call_count, 8)
        pairs = {(call.args[0], call.args[1]) for call in self.quotes.call_args_list}
        self.assertEqual(len(pairs), 8)
        self.assertEqual({day for _, day in pairs}, {DAY, END})

    def test_boundary_count_limit_precedes_requests_even_for_cash_only_plan(self):
        for index in range(17):
            self.record(cash(event_date=DAY + timedelta(days=index)))
        response = self.load(end_date=(DAY + timedelta(days=18)).isoformat())
        self.assertContains(response, "16 valuation dates", status_code=400)
        self.quotes.assert_not_called()

    def test_missing_middle_quote_withholds_complete_period_return(self):
        self.invested()
        self.record(cash(amount="50", event_date=MIDDLE))
        self.quotes.side_effect = lambda identifier, day, *_: (
            replace(history(as_of=day), observations=()) if day == MIDDLE else history(as_of=day)
        )
        response = self.load()
        self.assertContains(response, "complete-period return is unavailable")
        self.assertIsNone(response.context["performance"].return_percent)
        self.assertEqual(self.quotes.call_count, 3)

    def test_rate_limit_stops_later_boundaries_and_keeps_retry_header(self):
        self.invested()
        self.record(cash(amount="50", event_date=MIDDLE))
        self.quotes.side_effect = [history(as_of=DAY), ProviderRateLimited(120)]
        response = self.load()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["Retry-After"], "120")
        self.assertEqual(self.quotes.call_count, 2)
        self.assertIsNone(response.context["performance"].return_percent)
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_missing_key_and_unexpected_transport_errors_never_show_fake_returns(self):
        self.invested()
        self.quotes.side_effect = CredentialsMissing()
        self.assertContains(self.load(), "Intrinio is not configured", status_code=503)
        self.quotes.side_effect = RuntimeError(TEST_KEY)
        with self.assertLogs("research", level="ERROR") as logs:
            response = self.load()
        self.assertNotContains(response, TEST_KEY, status_code=503)
        self.assertNotIn(TEST_KEY, "\n".join(logs.output))
        self.assertIsNone(response.context["performance"].return_percent)

    def test_bad_journal_or_empty_opening_value_has_explicit_unavailability(self):
        response = self.load()
        self.assertContains(response, "positive opening value")
        self.assertIsNone(response.context["performance"].return_percent)
        with patch("ledger.performance.analyze", side_effect=LedgerRuleError("Bad history")):
            self.assertEqual(self.load().status_code, 503)
        self.quotes.assert_not_called()

    def test_foreign_missing_and_signed_out_requests_cannot_fetch_private_returns(self):
        for identifier in (self.foreign.pk, uuid.uuid4()):
            response = self.client.post(self.url(identifier), {"start_date": "bad"})
            self.assertEqual(response.status_code, 404)
            self.assertNotContains(response, "Private return secret", status_code=404)
            self.assertIn("no-store", response.headers["Cache-Control"])
        self.client.logout()
        response = self.load()
        self.assertEqual(response.status_code, 302)
        self.assertIn("/sign-in/?next=", response.url)
        self.quotes.assert_not_called()

    def test_csrf_and_method_guards_protect_quote_submissions(self):
        self.invested()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        data = {"start_date": DAY.isoformat(), "end_date": END.isoformat(), "timing_checked": "on"}
        response = client.post(self.url(), data)
        self.assertEqual(response.status_code, 403)
        self.assertIn("no-store", response.headers["Cache-Control"])
        for method in (self.client.put, self.client.head):
            self.assertEqual(method(self.url()).status_code, 405)
        self.quotes.assert_not_called()
        client.get(self.url())
        self.assertEqual(
            client.post(
                self.url(), {**data, "csrfmiddlewaretoken": client.cookies["csrftoken"].value}
            ).status_code,
            200,
        )

    def test_snapshot_is_read_once_and_later_append_does_not_change_returns(self):
        self.invested()
        before = list(Entry.objects.values())
        with self.assertNumQueries(2):
            _, result, _, _ = load_performance(self.owner, self.portfolio.pk, DAY, END, "127.0.0.1")
        self.assertEqual(result.return_percent, D("0.0000"))
        self.assertEqual(list(Entry.objects.values()), before)
        self.quotes.reset_mock()
        appended = False

        def load(identifier, day, *_):
            nonlocal appended
            if not appended:
                self.record(cash(amount="100", event_date=MIDDLE))
                appended = True
            return history("10", as_of=day)

        self.quotes.side_effect = load
        response = self.load()
        self.assertEqual(len(response.context["performance"].periods), 1)
        self.assertEqual(response.context["performance"].return_percent, D("0.0000"))
