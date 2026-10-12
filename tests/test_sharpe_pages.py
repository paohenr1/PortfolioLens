"""Private confirmed Sharpe loads reuse current journal and prices without writes."""

import uuid
from dataclasses import replace
from datetime import date
from decimal import Decimal
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase
from django.urls import reverse

from ledger.corrections import commit_correction, preview_correction
from ledger.models import Entry
from ledger.services import append_entry
from market_data.errors import ProviderRateLimited
from portfolios.services import create_portfolio
from tests.test_ledger import REFERENCE
from tests.test_ledger_domain import DAY, cash, trade
from tests.test_relationship_pages import END, FEE_DAY, relationship_history
from tests.test_valuation import IDENTIFIER

D = Decimal


@skipUnless(connection.vendor == "postgresql", "Private Sharpe tests require PostgreSQL")
class SharpePageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user("sharpe-owner")
        cls.other = get_user_model().objects.create_user("sharpe-other")
        cls.portfolio = create_portfolio(owner=cls.owner, name="Sharpe fixture")
        cls.foreign = create_portfolio(owner=cls.other, name="Foreign Sharpe secret")

    def setUp(self):
        self.client.force_login(self.owner)
        self.reference = patch("research.services.security_details", return_value=REFERENCE).start()
        self.prices = patch(
            "research.services.historical_prices",
            side_effect=lambda identifier, start, end, *_: relationship_history(
                identifier, start, end
            ),
        ).start()
        self.benchmark = patch("research.services.benchmark_prices").start()
        self.addCleanup(patch.stopall)
        self.record(cash())

    def record(self, intent):
        return append_entry(
            user=self.owner,
            portfolio_id=self.portfolio.pk,
            client_key=uuid.uuid4(),
            intent=intent,
            client_address="127.0.0.1",
        )

    def invested(self):
        self.record(trade(quantity="100", price="10", fees="0"))
        self.reference.reset_mock()

    def url(self, identifier=None):
        return reverse("portfolio_daily_returns", args=[identifier or self.portfolio.pk])

    def load(self, **values):
        return self.client.post(
            self.url(),
            {
                "start_date": DAY,
                "end_date": END,
                "timing_checked": "on",
                "annual_risk_free_percent": "0",
                "sharpe_assumption_checked": "on",
                **values,
            },
        )

    def test_get_has_no_assumed_rate_or_sharpe_and_requests_nothing(self):
        response = self.client.get(self.url(), {"annual_risk_free_percent": "4"})
        self.assertNotContains(response, 'id="sharpe-title"')
        self.assertNotIn("annual_risk_free_percent", response.context["form"].initial)
        self.prices.assert_not_called()

    def test_confirmed_zero_reuses_one_price_history_and_writes_nothing(self):
        self.invested()
        before = list(Entry.objects.values())
        response = self.load()
        result = response.context["sharpe"]
        self.assertEqual(result.observations, 20)
        self.assertEqual(result.daily_sharpe, D("0.0464"))
        self.assertEqual(result.annualized_sharpe, D("0.7368"))
        self.prices.assert_called_once()
        self.reference.assert_not_called()
        self.benchmark.assert_not_called()
        self.assertEqual(list(Entry.objects.values()), before)
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_blank_rate_preserves_no_sharpe_workflow(self):
        response = self.load(annual_risk_free_percent="", sharpe_assumption_checked="")
        self.assertIsNone(response.context["sharpe"])
        self.assertNotContains(response, 'id="sharpe-title"')

    def test_bad_unconfirmed_or_missing_rate_fails_before_provider_requests(self):
        for changes in (
            {"sharpe_assumption_checked": ""},
            {"annual_risk_free_percent": ""},
            {"annual_risk_free_percent": "NaN"},
            {"annual_risk_free_percent": "101"},
        ):
            self.assertEqual(self.load(**changes).status_code, 400)
        self.prices.assert_not_called()
        self.reference.assert_not_called()
        self.benchmark.assert_not_called()

    def test_foreign_missing_and_signed_out_requests_never_load_prices(self):
        for identifier in (self.foreign.pk, uuid.uuid4()):
            response = self.client.post(self.url(identifier), {"annual_risk_free_percent": "bad"})
            self.assertEqual(response.status_code, 404)
            self.assertNotContains(response, "Foreign Sharpe secret", status_code=404)
        self.client.logout()
        self.assertEqual(self.load().status_code, 302)
        self.prices.assert_not_called()

    def test_csrf_failure_precedes_sharpe_load(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        self.assertEqual(
            client.post(self.url(), {"annual_risk_free_percent": "0"}).status_code, 403
        )
        self.prices.assert_not_called()

    def test_short_complete_series_preserves_returns_but_withholds_sharpe(self):
        self.invested()
        response = self.load(end_date=date(2020, 1, 30))
        self.assertEqual(response.context["sharpe"].observations, 19)
        self.assertIsNone(response.context["sharpe"].daily_sharpe)
        self.assertIsNotNone(response.context["performance"].return_percent)

    def test_cash_only_zero_volatility_needs_no_provider(self):
        self.record(cash(amount="500", event_date=FEE_DAY))
        response = self.load(annual_risk_free_percent="4")
        self.assertEqual(response.context["sharpe"].mean_excess_percent, D("-0.0159"))
        self.assertIsNone(response.context["sharpe"].daily_sharpe)
        self.assertContains(response, "volatility is zero")
        self.prices.assert_not_called()

    def test_missing_session_withholds_full_sample(self):
        self.invested()
        history = relationship_history(IDENTIFIER)
        self.prices.side_effect = None
        self.prices.return_value = replace(
            history, observations=history.observations[:10] + history.observations[11:]
        )
        response = self.load()
        self.assertEqual(response.context["sharpe"].observations, 0)
        self.assertIsNone(response.context["sharpe"].daily_sharpe)

    def test_benchmark_failure_does_not_withhold_complete_portfolio_sharpe(self):
        self.invested()
        self.reference.side_effect = ProviderRateLimited(120)
        response = self.load(benchmark_id="sec_missing_benchmark")
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["Retry-After"], "120")
        self.assertEqual(response.context["sharpe"].annualized_sharpe, D("0.7368"))

    def test_portfolio_rate_limit_keeps_safe_unavailable_sharpe(self):
        self.invested()
        self.prices.side_effect = ProviderRateLimited(90)
        response = self.load()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["Retry-After"], "90")
        self.assertIsNone(response.context["sharpe"].daily_sharpe)

    def test_correction_restates_excess_and_sharpe_while_retaining_original_fee(self):
        fee = self.record(cash("FEE", "100", event_date=FEE_DAY))
        before = self.load(annual_risk_free_percent="4").context["sharpe"]
        intent = cash("FEE", "200", event_date=FEE_DAY)
        digest = preview_correction(
            user=self.owner,
            portfolio_id=self.portfolio.pk,
            target_id=fee.pk,
            intent=intent,
            reason="Fee correction",
        )[4]
        commit_correction(
            user=self.owner,
            portfolio_id=self.portfolio.pk,
            target_id=fee.pk,
            intent=intent,
            reason="Fee correction",
            client_key=uuid.uuid4(),
            expected_version=digest,
            client_address="127.0.0.1",
        )
        after = self.load(annual_risk_free_percent="4").context["sharpe"]
        self.assertEqual(before.mean_excess_percent, D("-0.5159"))
        self.assertEqual(after.mean_excess_percent, D("-1.0159"))
        self.assertEqual(before.daily_sharpe, D("-0.2307"))
        self.assertEqual(after.daily_sharpe, D("-0.2272"))
        self.assertEqual(Entry.objects.get(pk=fee.pk).amount, D(100))
        self.prices.assert_not_called()
