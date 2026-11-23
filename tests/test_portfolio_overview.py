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

from ledger.corrections import commit_correction, preview_correction
from ledger.models import Entry
from ledger.services import append_entry
from market_data.errors import EntitlementDenied, ProviderError, ProviderRateLimited
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
        return append_entry(
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

    @override_settings(PORTFOLIO_VALUATION_CACHE=True)
    def test_outage_uses_last_verified_dates_and_invalidates_changed_journal(self):
        self.record(cash(event_date=date(2019, 12, 2)))
        self.record(trade(event_date=date(2019, 12, 3), sequence=1))
        preference = reverse("portfolio_performance_preference", args=[self.portfolio.pk])
        self.client.post(preference, {"automatic_performance": "enable"})
        auto_url = reverse("portfolio_automatic_valuation", args=[self.portfolio.pk])
        self.quotes.side_effect = lambda identifier, day, address, **kwargs: history(
            "30" if day == date(2020, 1, 10) else "25", as_of=day
        )
        with patch("portfolios.automatic_valuation.ledger_today", return_value=date(2020, 1, 13)):
            initial = self.client.post(auto_url)
        self.assertContains(initial, "1,049.00")
        self.assertContains(initial, "5.0050%")
        self.assertNotContains(initial, "Stale")

        self.quotes.side_effect = ProviderError()
        with patch("portfolios.automatic_valuation.ledger_today", return_value=date(2020, 1, 14)):
            stale = self.client.post(auto_url)
            self.assertContains(stale, "Stale · Last verified close Jan 10, 2020", status_code=503)
            self.assertContains(
                stale, "Stale · Last verified return Dec 11, 2019 – Jan 10, 2020", status_code=503
            )
            self.assertContains(stale, "5.0050%", status_code=503)

            with override_settings(PORTFOLIO_VALUATION_CACHE=False):
                self.assertNotContains(self.client.post(auto_url), "Stale", status_code=503)
            self.quotes.side_effect = EntitlementDenied()
            self.assertNotContains(self.client.post(auto_url), "Stale", status_code=503)

            self.quotes.side_effect = ProviderError()
            self.record(cash(amount="50", event_date=date(2020, 1, 13)))
            changed = self.client.post(auto_url)
            self.assertNotContains(changed, "Stale", status_code=503)
            self.assertNotContains(changed, "1,049.00", status_code=503)
            self.assertNotContains(changed, "5.0050%", status_code=503)

    @override_settings(PORTFOLIO_VALUATION_CACHE=True)
    def test_entitlement_denial_prevents_fallback_even_when_other_security_has_outage(self):
        self.record(cash())
        self.record(trade(quantity="1"))
        second = "sec_fixture_second"
        self.reference.return_value = replace(
            REFERENCE, security=replace(REFERENCE.security, id=second)
        )
        self.record(trade(quantity="1", security_id=second, sequence=3))
        auto_url = reverse("portfolio_automatic_valuation", args=[self.portfolio.pk])
        self.quotes.side_effect = lambda identifier, day, address, **kwargs: history(
            "30", identifier=identifier, as_of=day
        )
        with patch("portfolios.automatic_valuation.ledger_today", return_value=date(2020, 1, 13)):
            self.assertContains(self.client.post(auto_url), "1,008.00")

        self.quotes.side_effect = [ProviderError(), EntitlementDenied()]
        with patch("portfolios.automatic_valuation.ledger_today", return_value=date(2020, 1, 14)):
            response = self.client.post(auto_url)
        self.assertNotContains(response, "Stale", status_code=503)
        self.assertNotContains(response, "1,008.00", status_code=503)

    @override_settings(PORTFOLIO_VALUATION_CACHE=True)
    def test_correction_committed_during_outage_request_invalidates_fallback(self):
        deposit = self.record(cash())
        self.record(trade())
        auto_url = reverse("portfolio_automatic_valuation", args=[self.portfolio.pk])
        self.quotes.side_effect = lambda identifier, day, address, **kwargs: history(
            "30", as_of=day
        )
        with patch("portfolios.automatic_valuation.ledger_today", return_value=date(2020, 1, 13)):
            self.assertContains(self.client.post(auto_url), "1,049.00")

        correction = {
            "user": self.user,
            "portfolio_id": self.portfolio.pk,
            "target_id": deposit.pk,
            "intent": cash(amount="1200"),
            "reason": "Correct recorded deposit",
        }
        version = preview_correction(**correction)[4]

        def outage_during_correction(*args, **kwargs):
            commit_correction(
                **correction,
                expected_version=version,
                client_key=uuid.uuid4(),
                client_address="127.0.0.1",
            )
            raise ProviderError()

        self.quotes.side_effect = outage_during_correction
        with patch("portfolios.automatic_valuation.ledger_today", return_value=date(2020, 1, 14)):
            response = self.client.post(auto_url)
        self.assertNotContains(response, "Stale", status_code=503)
        self.assertNotContains(response, "1,049.00", status_code=503)

    @override_settings(PORTFOLIO_VALUATION_CACHE=True)
    def test_return_with_changed_selected_dates_does_not_reuse_previous_return(self):
        self.record(cash())
        self.record(trade())
        self.client.post(
            reverse("portfolio_performance_preference", args=[self.portfolio.pk]),
            {"automatic_performance": "enable"},
        )
        auto_url = reverse("portfolio_automatic_valuation", args=[self.portfolio.pk])
        latest = date(2020, 1, 10)
        self.quotes.side_effect = lambda identifier, day, address, **kwargs: history(
            "30" if day == latest else "25", as_of=day
        )
        with patch("portfolios.automatic_valuation.ledger_today", return_value=date(2020, 1, 13)):
            self.assertEqual(
                self.client.post(self.url, {"start_date": DAY, "end_date": latest}).status_code,
                200,
            )
            self.assertContains(self.client.post(auto_url), "5.0050%")

            self.quotes.side_effect = ProviderError()
            self.assertEqual(
                self.client.post(
                    self.url, {"start_date": DAY + timedelta(days=1), "end_date": latest}
                ).status_code,
                503,
            )
            changed = self.client.post(auto_url)
        self.assertContains(changed, "Stale · Last verified close", status_code=503)
        self.assertNotContains(changed, "Last verified return", status_code=503)
        self.assertNotContains(changed, "5.0050%", status_code=503)

    def test_automatic_valuation_enforces_owner_post_and_csrf(self):
        url = reverse("portfolio_automatic_valuation", args=[self.portfolio.pk])
        foreign_url = reverse("portfolio_automatic_valuation", args=[self.foreign.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertNotContains(self.client.post(foreign_url), "Foreign secret", status_code=404)
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.user)
        self.assertEqual(protected.post(url).status_code, 403)
        self.quotes.assert_not_called()

    @override_settings(PORTFOLIO_VALUATION_CACHE=False)
    def test_opted_in_performance_reuses_closing_value_and_remembers_range(self):
        self.record(cash())
        self.record(trade())
        auto_url = reverse("portfolio_automatic_valuation", args=[self.portfolio.pk])
        preference = reverse("portfolio_performance_preference", args=[self.portfolio.pk])
        latest = date(2020, 1, 10)
        self.quotes.side_effect = lambda identifier, day, address, **kwargs: history(
            "25" if day == DAY else "30", as_of=day
        )

        with patch("portfolios.automatic_valuation.ledger_today", return_value=date(2020, 1, 13)):
            before = self.client.post(auto_url)
            self.assertNotContains(before, "Time-weighted return")
            self.quotes.assert_called_once()
            self.assertEqual(
                self.client.post(preference, {"automatic_performance": "enable"}).status_code, 302
            )
            self.assertEqual(self.quotes.call_count, 1)
            default = self.client.post(auto_url)
            self.assertEqual(default.context["period"], (date(2019, 12, 11), latest))
            self.assertContains(default, "deposits and withdrawals must follow")
            selection = self.client.post(self.url, {"start_date": DAY, "end_date": latest})
            self.assertEqual(selection.status_code, 200)
            self.assertContains(selection, "Turn off automatic performance")
            self.quotes.reset_mock()

            automatic = self.client.post(auto_url)
            self.assertEqual(automatic.context["period"], (DAY, latest))
            self.assertContains(automatic, "5.0050%")
            self.assertContains(automatic, "1,049.00")
            self.assertEqual([call.args[1] for call in self.quotes.call_args_list], [latest, DAY])
            self.assertTrue(
                all(call.kwargs == {"background": True} for call in self.quotes.call_args_list)
            )

            self.assertEqual(
                self.client.post(preference, {"automatic_performance": "disable"}).status_code, 302
            )
            self.assertNotContains(self.client.post(auto_url), "Time-weighted return")

    def test_automatic_performance_preflight_keeps_latest_value_when_range_needs_extra_quote(self):
        self.record(cash())
        self.record(trade())
        self.quotes.side_effect = lambda identifier, day, address, **kwargs: history(
            "30", as_of=day
        )
        self.client.post(self.url, self.data)
        self.client.post(
            reverse("portfolio_performance_preference", args=[self.portfolio.pk]),
            {"automatic_performance": "enable"},
        )
        self.quotes.reset_mock()
        with patch("portfolios.automatic_valuation.ledger_today", return_value=date(2020, 1, 13)):
            automatic = self.client.post(
                reverse("portfolio_automatic_valuation", args=[self.portfolio.pk])
            )
        self.assertContains(automatic, "1,049.00")
        self.assertContains(automatic, "This period needs manual performance analysis.")
        self.quotes.assert_called_once()

    def test_automatic_perf_preference_is_private_and_csrf_protected(self):
        preference = reverse("portfolio_performance_preference", args=[self.portfolio.pk])
        foreign = reverse("portfolio_performance_preference", args=[self.foreign.pk])
        data = {"automatic_performance": "enable"}
        self.assertEqual(self.client.get(preference).status_code, 405)
        self.assertEqual(self.client.post(foreign, data).status_code, 404)
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.user)
        self.assertEqual(protected.post(preference, data).status_code, 403)
        self.portfolio.refresh_from_db()
        self.foreign.refresh_from_db()
        self.assertFalse(self.portfolio.automatic_performance_enabled)
        self.assertFalse(self.foreign.automatic_performance_enabled)

    def test_cash_only_historical_return_can_load_even_when_current_valuation_exceeds_budget(self):
        self.record(cash())
        self.client.post(self.url, self.data)
        for number in range(3):
            security_id = f"sec_later_{number}"
            self.reference.return_value = replace(
                REFERENCE, security=replace(REFERENCE.security, id=security_id)
            )
            self.record(
                trade(
                    quantity="1",
                    sequence=number + 1,
                    event_date=date(2020, 1, 9),
                    security_id=security_id,
                )
            )
        self.client.post(
            reverse("portfolio_performance_preference", args=[self.portfolio.pk]),
            {"automatic_performance": "enable"},
        )
        with patch("portfolios.automatic_valuation.ledger_today", return_value=date(2020, 1, 13)):
            response = self.client.post(
                reverse("portfolio_automatic_valuation", args=[self.portfolio.pk])
            )
        self.assertContains(response, "Open manual valuation")
        self.assertContains(response, "0.0000%")
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
