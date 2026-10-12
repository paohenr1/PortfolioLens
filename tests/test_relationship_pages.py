"""Relationship metrics on private PostgreSQL snapshots and corrected journals."""

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
from ledger.daily_returns import session_dates
from ledger.models import Entry
from ledger.services import append_entry
from market_data.contracts import DailyPrice
from market_data.errors import ProviderRateLimited
from portfolios.services import create_portfolio
from tests.test_benchmarks import BENCHMARK_ID, BENCHMARK_REFERENCE
from tests.test_daily_return_pages import range_history
from tests.test_ledger import REFERENCE
from tests.test_ledger_domain import DAY, cash, trade
from tests.test_valuation import IDENTIFIER

D = Decimal
END = date(2020, 1, 31)
FEE_DAY = date(2020, 1, 15)


def relationship_history(identifier, start=DAY, end=END):
    history = range_history(identifier, start, end)
    return replace(
        history,
        observations=tuple(
            DailyPrice(day, D(10 if index % 2 == 0 else 11), D(10 if index % 2 == 0 else 11), False)
            for index, day in enumerate(session_dates(start, end))
        ),
    )


@skipUnless(connection.vendor == "postgresql", "Private relationship tests require PostgreSQL")
class RelationshipPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user("relationship-owner")
        cls.portfolio = create_portfolio(owner=cls.owner, name="Relationship fixture")

    def setUp(self):
        self.client.force_login(self.owner)
        self.reference = patch(
            "research.services.security_details", return_value=BENCHMARK_REFERENCE
        ).start()
        self.prices = patch(
            "research.services.historical_prices",
            side_effect=lambda identifier, start, end, *_: relationship_history(
                identifier, start, end
            ),
        ).start()
        self.benchmark = patch(
            "research.services.benchmark_prices",
            side_effect=lambda identifier, start, end, *_: relationship_history(
                identifier, start, end
            ),
        ).start()
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
        self.reference.return_value = REFERENCE
        self.record(trade(quantity="100", price="10", fees="0"))
        self.reference.return_value = BENCHMARK_REFERENCE
        self.reference.reset_mock()

    def url(self):
        return reverse("portfolio_daily_returns", args=[self.portfolio.pk])

    def load(self, **values):
        return self.client.post(
            self.url(),
            {
                "start_date": DAY,
                "end_date": END,
                "timing_checked": "on",
                "benchmark_id": BENCHMARK_ID,
                **values,
            },
        )

    def test_get_has_no_relationship_claim_or_provider_requests(self):
        response = self.client.get(self.url())
        self.assertNotContains(response, 'id="relationship-title"')
        self.reference.assert_not_called()
        self.prices.assert_not_called()
        self.benchmark.assert_not_called()

    def test_twenty_returns_show_coefficients_with_no_additional_calls_or_writes(self):
        self.invested()
        before = list(Entry.objects.values())
        response = self.load()
        relationship = response.context["comparison"].relationship
        self.assertEqual(relationship.observations, 20)
        self.assertEqual(relationship.correlation, D(1))
        self.assertEqual(relationship.beta, D(1))
        self.assertContains(response, "Correlation and beta · matched daily returns")
        self.assertContains(response, "Beta · selected benchmark")
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.prices.assert_called_once()
        self.reference.assert_called_once()
        self.benchmark.assert_called_once()
        self.assertEqual(list(Entry.objects.values()), before)

    def test_nineteen_returns_keep_comparison_and_explain_unavailable_statistics(self):
        self.invested()
        response = self.load(end_date=date(2020, 1, 30))
        result = response.context["comparison"]
        self.assertIsNone(result.issue)
        self.assertIsNone(result.relationship.beta)
        self.assertEqual(result.relationship.observations, 19)
        self.assertContains(response, "at least twenty matched session returns")

    def test_cash_and_funding_have_zero_slope_but_undefined_correlation(self):
        self.record(cash(amount="500", event_date=FEE_DAY))
        response = self.load()
        relationship = response.context["comparison"].relationship
        self.assertEqual(relationship.beta, D(0))
        self.assertIsNone(relationship.correlation)
        self.assertContains(response, "Portfolio return variance is zero")
        self.prices.assert_not_called()
        self.benchmark.assert_called_once()

    def test_constant_benchmark_withholds_both_even_with_varying_portfolio(self):
        self.invested()
        self.benchmark.side_effect = lambda identifier, start, end, *_: range_history(
            identifier, start, end
        )
        response = self.load()
        relationship = response.context["comparison"].relationship
        self.assertIsNone(relationship.correlation)
        self.assertIsNone(relationship.beta)
        self.assertContains(response, "Benchmark return variance is zero")

    def test_missing_middle_quote_does_not_reduce_sample_and_report_statistics(self):
        self.invested()
        history = relationship_history(BENCHMARK_ID)
        self.benchmark.side_effect = None
        self.benchmark.return_value = replace(
            history, observations=history.observations[:10] + history.observations[11:]
        )
        response = self.load()
        relationship = response.context["comparison"].relationship
        self.assertEqual(relationship.observations, 0)
        self.assertIsNone(relationship.beta)
        self.assertContains(response, "complete valid matched daily series")

    def test_same_instrument_relationship_reuses_one_history(self):
        self.invested()
        self.reference.return_value = REFERENCE
        response = self.load(benchmark_id=IDENTIFIER)
        self.assertEqual(response.context["comparison"].relationship.beta, D(1))
        self.prices.assert_called_once()
        self.benchmark.assert_not_called()

    def test_corrected_fee_restates_slope_and_preserves_original_journal(self):
        fee = self.record(cash("FEE", "100", event_date=FEE_DAY))
        relationship = self.load().context["comparison"].relationship
        self.assertEqual(relationship.beta, D("-0.0524"))  # -11 / 210
        self.assertEqual(relationship.correlation, D("-0.2294"))  # -1 / sqrt(19)
        intent = cash("FEE", "200", event_date=FEE_DAY)
        digest = preview_correction(
            user=self.owner,
            portfolio_id=self.portfolio.pk,
            target_id=fee.pk,
            intent=intent,
            reason="Correct transcribed fee",
        )[4]
        commit_correction(
            user=self.owner,
            portfolio_id=self.portfolio.pk,
            target_id=fee.pk,
            intent=intent,
            reason="Correct transcribed fee",
            client_key=uuid.uuid4(),
            expected_version=digest,
            client_address="127.0.0.1",
        )
        result = self.load().context["comparison"].relationship
        self.assertEqual(result.beta, D("-0.1048"))  # -11 / 105
        self.assertEqual(result.correlation, relationship.correlation)
        self.assertEqual(Entry.objects.get(pk=fee.pk).amount, D(100))
        self.prices.assert_not_called()
        self.assertEqual(self.benchmark.call_count, 2)

    def test_rate_limit_keeps_relationship_unavailable(self):
        self.benchmark.side_effect = ProviderRateLimited(120)
        response = self.load()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["Retry-After"], "120")
        self.assertIsNone(response.context["comparison"].relationship.beta)
        self.benchmark.assert_called_once()
