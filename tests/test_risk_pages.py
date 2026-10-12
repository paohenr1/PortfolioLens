"""Risk integration on actual private PostgreSQL journals; no live provider data."""

import uuid
from dataclasses import replace
from datetime import date
from decimal import Decimal
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.urls import reverse

from ledger.corrections import commit_correction, preview_correction
from ledger.models import Entry
from ledger.services import append_entry
from market_data.errors import ProviderRateLimited
from portfolios.services import create_portfolio
from tests.test_daily_return_pages import END, MIDDLE, range_history
from tests.test_ledger import REFERENCE
from tests.test_ledger_domain import DAY, cash, trade

D = Decimal


@skipUnless(connection.vendor == "postgresql", "Private risk integration requires PostgreSQL")
class RiskPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user("risk-owner")
        cls.portfolio = create_portfolio(owner=cls.owner, name="Risk example")

    def setUp(self):
        self.client.force_login(self.owner)
        patch("ledger.services.market_data.security_details", return_value=REFERENCE).start()
        self.prices = patch(
            "ledger.daily_return_services.market_data.historical_prices",
            side_effect=lambda identifier, start, end, *_: range_history(identifier, start, end),
        ).start()
        self.addCleanup(patch.stopall)
        self.record(cash())
        self.record(trade(price="10", fees="0"))

    def record(self, intent):
        return append_entry(
            user=self.owner,
            portfolio_id=self.portfolio.pk,
            client_key=uuid.uuid4(),
            intent=intent,
            client_address="127.0.0.1",
        )

    def load(self, end=END):
        return self.client.post(
            reverse("portfolio_daily_returns", args=[self.portfolio.pk]),
            {"start_date": DAY, "end_date": end, "timing_checked": "on"},
        )

    def test_get_does_not_load_or_claim_risk(self):
        response = self.client.get(reverse("portfolio_daily_returns", args=[self.portfolio.pk]))
        self.assertNotIn("risk", response.context)
        self.assertNotContains(response, 'id="risk-title"')
        self.prices.assert_not_called()

    def test_risk_reuses_single_history_and_writes_no_records(self):
        before = list(Entry.objects.values())
        response = self.load()
        result = response.context["risk"]
        self.assertEqual(result.observations, 4)
        self.assertEqual(result.daily_volatility_percent, D(0))
        self.assertIsNone(result.annualized_volatility_percent)
        self.assertEqual(result.maximum_drawdown_percent, D(0))
        self.assertEqual(len(result.rows), 5)
        self.assertContains(response, "Volatility and drawdown")
        self.assertContains(response, "research/prices.js")
        self.assertContains(response, "Drawdown observation table")
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.prices.assert_called_once()
        self.assertEqual(list(Entry.objects.values()), before)

    def test_deposit_raising_dollar_balance_does_not_hide_return_drawdown(self):
        self.record(cash(amount="500", event_date=MIDDLE))
        original = range_history()
        self.prices.side_effect = None
        self.prices.return_value = replace(
            original,
            observations=tuple(
                replace(p, close=D(20)) if p.date == date(2020, 1, 3) else p
                for p in original.observations
            ),
        )
        response = self.load()
        result = response.context["risk"]
        self.assertEqual(result.maximum_drawdown_percent, D("9.0909"))
        self.assertEqual(result.peak_date, date(2020, 1, 3))
        self.assertEqual(result.trough_date, MIDDLE)
        self.assertIsNone(result.recovery_date)
        self.assertEqual(response.context["valuations"][-1].total_value, D(1500))
        self.prices.assert_called_once()

    def test_missing_session_hides_entire_risk_chart(self):
        original = range_history()
        self.prices.side_effect = None
        self.prices.return_value = replace(
            original, observations=tuple(p for p in original.observations if p.date != MIDDLE)
        )
        response = self.load()
        self.assertIsNone(response.context["risk"].daily_volatility_percent)
        self.assertIsNone(response.context["risk"].maximum_drawdown_percent)
        self.assertIsNone(response.context["drawdown_chart"])
        self.assertNotContains(response, 'id="drawdown-title"')
        self.assertContains(response, "Missing or invalid rows are not dropped")

    def test_one_return_supports_drawdown_but_withholds_volatility(self):
        response = self.load(end=date(2020, 1, 3))
        result = response.context["risk"]
        self.assertEqual(result.observations, 1)
        self.assertIsNone(result.daily_volatility_percent)
        self.assertEqual(result.maximum_drawdown_percent, D(0))
        self.assertContains(response, "at least two session returns")

    def test_long_complete_sample_enables_annualized_volatility(self):
        response = self.load(end=date(2020, 2, 3))
        result = response.context["risk"]
        self.assertEqual(result.observations, 21)
        self.assertEqual(result.annualized_volatility_percent, D(0))
        self.assertIsNone(result.annualization_issue)
        self.prices.assert_called_once()

    def test_correction_restates_drawdown_and_keeps_original_fee(self):
        fee = self.record(cash("FEE", "10", event_date=MIDDLE))
        self.assertEqual(self.load().context["risk"].maximum_drawdown_percent, D(1))
        intent = cash("FEE", "20", event_date=MIDDLE)
        digest = preview_correction(
            user=self.owner,
            portfolio_id=self.portfolio.pk,
            target_id=fee.pk,
            intent=intent,
            reason="Fee transcription correction",
        )[4]
        commit_correction(
            user=self.owner,
            portfolio_id=self.portfolio.pk,
            target_id=fee.pk,
            intent=intent,
            reason="Fee transcription correction",
            client_key=uuid.uuid4(),
            expected_version=digest,
            client_address="127.0.0.1",
        )
        self.assertEqual(self.load().context["risk"].maximum_drawdown_percent, D(2))
        self.assertEqual(Entry.objects.get(pk=fee.pk).amount, D(10))
        self.assertEqual(self.prices.call_count, 2)

    def test_rate_limit_preserves_safe_response_and_unavailable_risk(self):
        self.prices.side_effect = ProviderRateLimited(120)
        response = self.load()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["Retry-After"], "120")
        self.assertIsNone(response.context["risk"].maximum_drawdown_percent)
        self.assertIsNone(response.context["drawdown_chart"])
        self.prices.assert_called_once()
