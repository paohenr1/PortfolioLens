"""Private PostgreSQL snapshots, corrected history, and bounded range transports."""

import uuid
from dataclasses import replace
from datetime import date
from decimal import Decimal
from unittest import skipUnless
from unittest.mock import patch

import httpx
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from ledger.corrections import commit_correction, preview_correction
from ledger.daily_return_services import load_daily_returns
from ledger.daily_returns import session_dates
from ledger.models import Entry
from ledger.services import append_entry
from market_data.errors import CredentialsMissing, ProviderRateLimited
from market_data.intrinio import IntrinioClient
from portfolios.services import create_portfolio
from research.services import _request_budget
from tests.test_intrinio import TEST_KEY
from tests.test_ledger import REFERENCE
from tests.test_ledger_domain import DAY, cash, trade
from tests.test_valuation import IDENTIFIER, history

D = Decimal
END = date(2020, 1, 8)
MIDDLE = date(2020, 1, 6)


def range_history(identifier=IDENTIFIER, start=DAY, end=END):
    return replace(
        history("10", identifier=identifier),
        start_date=start,
        end_date=end,
        observations=tuple(
            history("10", identifier=identifier, as_of=day).observations[0]
            for day in session_dates(start, end)
        ),
    )


@skipUnless(connection.vendor == "postgresql", "Daily returns require PostgreSQL")
class DailyReturnPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user("daily-owner")
        cls.other = get_user_model().objects.create_user("daily-other")
        cls.portfolio = create_portfolio(owner=cls.owner, name="Daily fixture")
        cls.foreign = create_portfolio(owner=cls.other, name="Foreign daily secret")

    def setUp(self):
        self.client.force_login(self.owner)
        self.reference = patch(
            "ledger.services.market_data.security_details", return_value=REFERENCE
        ).start()
        self.prices = patch(
            "ledger.daily_return_services.market_data.historical_prices",
            side_effect=lambda identifier, start, end, *_: range_history(identifier, start, end),
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

    def invested(self):
        self.record(cash())
        return self.record(trade(price="10", fees="0"))

    def url(self, identifier=None):
        return reverse("portfolio_daily_returns", args=[identifier or self.portfolio.pk])

    def load(self, **values):
        return self.client.post(
            self.url(), {"start_date": DAY, "end_date": END, "timing_checked": "on", **values}
        )

    def add_instrument(self, identifier, sequence):
        self.reference.return_value = replace(
            REFERENCE, security=replace(REFERENCE.security, id=identifier)
        )
        self.record(
            trade(quantity="1", price="10", fees="0", sequence=sequence, security_id=identifier)
        )

    def test_get_ignores_load_flags_and_requests_nothing(self):
        response = self.client.get(self.url(), {"load": "1", "start_date": DAY})
        self.assertContains(response, "Load daily returns")
        self.assertNotIn("performance", response.context)
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.prices.assert_not_called()

    def test_range_fetched_once_four_daily_rows_no_writes(self):
        self.invested()
        before = list(Entry.objects.values())
        response = self.load()
        self.assertEqual(response.context["performance"].return_percent, D(0))
        self.assertEqual(len(response.context["performance"].periods), 4)
        self.prices.assert_called_once_with(IDENTIFIER, DAY, END, "127.0.0.1")
        self.assertContains(response, "retrieved")
        self.assertEqual(list(Entry.objects.values()), before)

    def test_cash_only_all_sessions_no_provider_requests(self):
        self.record(cash())
        self.record(cash(amount="50", event_date=MIDDLE))
        response = self.load()
        self.assertEqual(response.context["performance"].return_percent, D(0))
        self.assertEqual(len(response.context["valuations"]), 5)
        self.prices.assert_not_called()

    def test_empty_baseline_reports_unavailable_without_prices(self):
        self.assertContains(self.load(), "positive opening value")
        self.prices.assert_not_called()

    def test_missing_middle_session_does_not_bridge_gap(self):
        self.invested()
        original = range_history()
        self.prices.side_effect = None
        self.prices.return_value = replace(
            original, observations=tuple(p for p in original.observations if p.date != MIDDLE)
        )
        result = self.load().context["performance"]
        self.assertIsNone(result.return_percent)
        self.assertEqual(
            [p.return_percent is None for p in result.periods], [False, True, True, False]
        )

    def test_unconfirmed_close_and_adjusted_only_leave_required_session_unknown(self):
        self.invested()
        original = range_history()
        self.prices.side_effect = None
        for close, intraperiod in ((None, False), (D(10), None), (D(10), True)):
            self.prices.return_value = replace(
                original,
                observations=tuple(
                    replace(p, close=close, intraperiod=intraperiod) if p.date == MIDDLE else p
                    for p in original.observations
                ),
            )
            self.assertIsNone(self.load().context["performance"].return_percent)

    def test_incomplete_mismatched_duplicate_or_outside_range_histories_fail_closed(self):
        self.invested()
        original = range_history()
        self.prices.side_effect = None
        for bad in (
            replace(original, pagination_complete=False),
            replace(original, start_date=MIDDLE),
            replace(original, security=replace(original.security, id="wrong_id")),
            replace(original, security=replace(original.security, currency="EUR")),
            replace(original, security=replace(original.security, exchange_mic="XNAS")),
            replace(original, observations=(*original.observations, original.observations[0])),
            replace(
                original,
                observations=(
                    *original.observations,
                    replace(original.observations[0], date=date(2020, 1, 9)),
                ),
            ),
        ):
            with self.subTest(history=bad):
                self.prices.return_value = bad
                self.assertIsNone(self.load().context["performance"].return_percent)

    def test_two_instruments_each_requested_once(self):
        self.invested()
        self.add_instrument("sec_fixture_other", 3)
        self.assertEqual(self.load().context["performance"].return_percent, D(0))
        self.assertEqual(self.prices.call_count, 2)

    def test_sold_holding_still_required_and_cap_precedes_fetch(self):
        self.invested()
        self.record(trade("SELL", price="10", fees="0", sequence=1, event_date=MIDDLE))
        self.load()
        self.prices.assert_called_once()
        self.add_instrument("sec_fixture_other", 3)
        self.add_instrument("sec_fixture_third", 4)
        self.prices.reset_mock()
        self.assertContains(self.load(), "at most two instruments", status_code=400)
        self.prices.assert_not_called()

    def test_non_session_and_intraday_activity_rejected_before_fetch(self):
        self.invested()
        self.record(cash("FEE", "1", event_date=date(2020, 1, 4)))
        self.assertContains(self.load(), "Non-session activity", status_code=400)
        self.prices.assert_not_called()

    def test_bad_dates_and_unconfirmed_timing_never_fetch(self):
        for data in (
            {"end_date": "2020-01-04"},
            {"start_date": "2020-01-01"},
            {"start_date": "bad"},
            {"start_date": "1999-12-30"},
            {"end_date": "2020-04-01"},
            {"timing_checked": ""},
        ):
            with self.subTest(data=data):
                self.assertEqual(self.load(**data).status_code, 400)
        self.prices.assert_not_called()

    def test_rate_limit_stops_second_instrument_and_preserves_retry(self):
        self.invested()
        self.add_instrument("sec_fixture_other", 3)
        self.prices.side_effect = ProviderRateLimited(120)
        response = self.load()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["Retry-After"], "120")
        self.assertIsNone(response.context["performance"].return_percent)
        self.assertEqual(self.prices.call_count, 1)

    def test_missing_key_and_unexpected_exception_are_safe(self):
        self.invested()
        self.prices.side_effect = CredentialsMissing()
        self.assertEqual(self.load().status_code, 503)
        self.prices.side_effect = RuntimeError("private-credential-and-url")
        with self.assertLogs("research", level="ERROR") as logs:
            response = self.load()
        self.assertNotContains(response, "private-credential-and-url", status_code=503)
        self.assertNotIn("private-credential-and-url", str(logs.output))

    def test_foreign_missing_signed_out_csrf_methods_and_cache(self):
        for identifier in (self.foreign.pk, uuid.uuid4()):
            response = self.client.post(self.url(identifier), {"start_date": "bad"})
            self.assertEqual(response.status_code, 404)
            self.assertNotContains(response, "Foreign daily secret", status_code=404)
            self.assertIn("no-store", response.headers["Cache-Control"])
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.owner)
        self.assertEqual(csrf.post(self.url(), {}).status_code, 403)
        self.assertEqual(self.client.put(self.url()).status_code, 405)
        self.assertEqual(self.client.head(self.url()).status_code, 405)
        self.client.logout()
        self.assertIn("/sign-in/?next=", self.load().url)
        self.prices.assert_not_called()

    def test_one_snapshot_and_append_during_history_does_not_change_series(self):
        self.invested()
        with self.assertNumQueries(2):
            _, result, _, _ = load_daily_returns(
                self.owner, self.portfolio.pk, DAY, END, "127.0.0.1"
            )
        self.assertEqual(result.return_percent, D(0))

        def later(*args):
            self.record(cash("FEE", "10", event_date=MIDDLE))
            return range_history()

        self.prices.side_effect = later
        self.assertEqual(self.load().context["performance"].return_percent, D(0))
        self.prices.side_effect = lambda *args: range_history()
        self.assertEqual(self.load().context["performance"].return_percent, D("-1.0000"))

    def test_corrected_journal_restates_daily_returns_without_original_mutation(self):
        buy = self.invested()
        original = Entry.objects.values().get(pk=buy.pk)
        intent = trade(price="20", fees="0")
        digest = preview_correction(
            user=self.owner,
            portfolio_id=self.portfolio.pk,
            target_id=buy.pk,
            intent=intent,
            reason="Execution correction",
        )[4]
        commit_correction(
            user=self.owner,
            portfolio_id=self.portfolio.pk,
            target_id=buy.pk,
            intent=intent,
            reason="Execution correction",
            client_key=uuid.uuid4(),
            expected_version=digest,
            client_address="127.0.0.1",
        )
        response = self.load()
        self.assertEqual(response.context["valuations"][0].total_value, D(900))
        self.assertEqual(Entry.objects.values().get(pk=buy.pk), original)

    @override_settings(INTRINIO_API_KEY=TEST_KEY)
    def test_actual_paginated_transport_is_bounded_to_eight_and_reserves_each_page(self):
        self.invested()
        self.add_instrument("sec_fixture_other", 3)
        patch.stopall()
        _request_budget.reset()
        self.addCleanup(_request_budget.reset)
        calls = []
        days = session_dates(DAY, END)

        def handler(request):
            calls.append(request)
            identifier = request.url.path.split("/")[2]
            page = int(request.url.params.get("next_page", "0"))
            return httpx.Response(
                200,
                json={
                    "security": {
                        "id": identifier,
                        "ticker": "TSTF",
                        "exchange_mic": "XNYS",
                        "currency": "USD",
                    },
                    "stock_prices": [
                        {
                            "date": day.isoformat(),
                            "frequency": "daily",
                            "close": 10,
                            "intraperiod": False,
                        }
                        for day in (days[page : page + 1] if page < 3 else days[3:])
                    ],
                    "next_page": str(page + 1) if page < 3 else None,
                },
            )

        with patch(
            "research.services.IntrinioClient",
            side_effect=lambda key: IntrinioClient(key, transport=httpx.MockTransport(handler)),
        ):
            self.assertEqual(self.load().context["performance"].return_percent, D(0))
        self.assertEqual(len(calls), 8)
        self.assertEqual(_request_budget._total, 8)
        self.assertTrue(
            all(
                r.url.params["start_date"] == DAY.isoformat()
                and r.url.params["end_date"] == END.isoformat()
                for r in calls
            )
        )


class DailyReturnStorageGuardTests(SimpleTestCase):
    def test_sqlite_private_route_is_unavailable_before_provider_calls(self):
        with (
            patch("portfolios.services.connection.vendor", "sqlite"),
            patch("ledger.daily_return_services.market_data.historical_prices") as prices,
        ):
            from portfolios.services import PortfolioStorageUnavailable

            with self.assertRaises(PortfolioStorageUnavailable):
                load_daily_returns(None, uuid.uuid4(), DAY, END, "127.0.0.1")
        prices.assert_not_called()
