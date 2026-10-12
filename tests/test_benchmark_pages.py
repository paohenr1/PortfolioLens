"""Private comparison boundaries, snapshot consistency, and actual bounded HTTP loads."""

import uuid
from dataclasses import replace
from unittest import skipUnless
from unittest.mock import patch

import httpx
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from ledger.daily_return_services import load_daily_comparison
from ledger.models import Entry
from ledger.services import append_entry
from market_data.errors import ProviderRateLimited
from market_data.intrinio import IntrinioClient
from portfolios.services import create_portfolio
from research.services import _request_budget
from tests.test_benchmarks import BENCHMARK_ID, BENCHMARK_REFERENCE, benchmark_history
from tests.test_daily_return_pages import END, range_history
from tests.test_intrinio import TEST_KEY
from tests.test_ledger import REFERENCE
from tests.test_ledger_domain import DAY, cash, trade
from tests.test_risk import fixture_series
from tests.test_valuation import IDENTIFIER


@skipUnless(connection.vendor == "postgresql", "Benchmark comparisons require PostgreSQL")
class BenchmarkPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user("benchmark-owner")
        cls.other = get_user_model().objects.create_user("benchmark-other")
        cls.portfolio = create_portfolio(owner=cls.owner, name="Benchmark fixture")
        cls.foreign = create_portfolio(owner=cls.other, name="Foreign benchmark secret")

    def setUp(self):
        self.client.force_login(self.owner)
        self.reference = patch(
            "research.services.security_details", return_value=BENCHMARK_REFERENCE
        ).start()
        self.prices = patch(
            "research.services.historical_prices",
            side_effect=lambda identifier, start, end, *_: range_history(identifier, start, end),
        ).start()
        series = fixture_series(["100"] * 5)
        self.benchmark = patch(
            "research.services.benchmark_prices", return_value=benchmark_history(series)
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
        self.reference.return_value = REFERENCE
        self.record(trade(price="10", fees="0"))
        self.reference.return_value = BENCHMARK_REFERENCE
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
                "benchmark_id": BENCHMARK_ID,
                **values,
            },
        )

    def test_get_requests_no_reference_prices_or_comparison(self):
        response = self.client.get(self.url(), {"benchmark_id": BENCHMARK_ID})
        self.assertContains(response, "Optional benchmark security ID")
        self.assertNotIn("comparison", response.context)
        self.reference.assert_not_called()
        self.prices.assert_not_called()
        self.benchmark.assert_not_called()

    def test_blank_selection_preserves_existing_zero_extra_request_workflow(self):
        self.invested()
        response = self.load(benchmark_id="")
        self.assertIsNone(response.context["comparison"])
        self.reference.assert_not_called()
        self.benchmark.assert_not_called()
        self.prices.assert_called_once()

    def test_complete_comparison_is_private_and_writes_nothing(self):
        self.invested()
        before = list(Entry.objects.values())
        response = self.load()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["comparison"].difference_points, 0)
        self.assertEqual(len(response.context["comparison"].rows), 4)
        self.assertContains(response, "adjustment methodology and index tracking")
        self.assertContains(response, "Benchmark comparison table")
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(list(Entry.objects.values()), before)
        self.reference.assert_called_once_with(BENCHMARK_ID, "127.0.0.1")
        self.benchmark.assert_called_once_with(BENCHMARK_ID, DAY, END, "127.0.0.1")

    def test_cash_only_comparison_loads_benchmark_and_no_portfolio_prices(self):
        self.record(cash())
        response = self.load()
        self.assertEqual(response.context["comparison"].difference_points, 0)
        self.prices.assert_not_called()
        self.reference.assert_called_once()
        self.benchmark.assert_called_once()

    def test_same_instrument_reuses_loaded_history(self):
        self.invested()
        self.reference.return_value = REFERENCE
        response = self.load(benchmark_id=IDENTIFIER)
        self.assertIsNone(response.context["comparison"].issue)
        self.prices.assert_called_once()
        self.benchmark.assert_not_called()

    def test_foreign_missing_and_signed_out_requests_do_not_access_provider(self):
        for identifier in (self.foreign.pk, uuid.uuid4()):
            response = self.client.post(self.url(identifier), {"benchmark_id": BENCHMARK_ID})
            self.assertEqual(response.status_code, 404)
            self.assertNotContains(response, "Foreign benchmark secret", status_code=404)
        self.client.logout()
        self.assertEqual(self.load().status_code, 302)
        self.reference.assert_not_called()
        self.benchmark.assert_not_called()

    def test_missing_csrf_cannot_request_benchmark(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        self.assertEqual(client.post(self.url(), {"benchmark_id": BENCHMARK_ID}).status_code, 403)
        self.reference.assert_not_called()
        self.benchmark.assert_not_called()

    def test_invalid_id_dates_or_confirmation_fail_before_all_data_requests(self):
        for changes in (
            {"benchmark_id": "../escape"},
            {"benchmark_id": "x" * 101},
            {"start_date": "2020-01-04"},
            {"timing_checked": ""},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(self.load(**changes).status_code, 400)
        self.reference.assert_not_called()
        self.prices.assert_not_called()
        self.benchmark.assert_not_called()

    def test_unsupported_benchmark_requests_no_price_history(self):
        self.record(cash())
        self.reference.return_value = replace(
            BENCHMARK_REFERENCE, security=replace(BENCHMARK_REFERENCE.security, currency="CAD")
        )
        response = self.load()
        self.assertContains(response, "Choose a USD security")
        self.assertIsNone(response.context["comparison"].difference_points)
        self.benchmark.assert_not_called()

    def test_missing_benchmark_keeps_portfolio_return_and_risk(self):
        self.invested()
        history = self.benchmark.return_value
        self.benchmark.return_value = replace(history, observations=history.observations[::2])
        response = self.load()
        self.assertEqual(response.context["performance"].return_percent, 0)
        self.assertEqual(response.context["risk"].maximum_drawdown_percent, 0)
        self.assertIsNone(response.context["comparison_chart"])
        self.assertIsNone(response.context["comparison"].difference_points)

    def test_missing_portfolio_session_prevents_partial_comparison(self):
        self.invested()
        self.prices.side_effect = None
        history = range_history()
        self.prices.return_value = replace(history, observations=history.observations[::2])
        response = self.load()
        self.assertIsNone(response.context["comparison"].difference_points)
        self.assertEqual(response.context["comparison"].rows, ())

    def test_portfolio_rate_limit_stops_benchmark_requests(self):
        self.invested()
        self.prices.side_effect = ProviderRateLimited(120)
        response = self.load()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["Retry-After"], "120")
        self.reference.assert_not_called()
        self.benchmark.assert_not_called()

    def test_benchmark_rate_limit_preserves_complete_portfolio_results(self):
        self.invested()
        self.benchmark.side_effect = ProviderRateLimited(90)
        response = self.load()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["Retry-After"], "90")
        self.assertEqual(response.context["performance"].return_percent, 0)
        self.assertIsNone(response.context["comparison"].difference_points)

    def test_unexpected_failure_does_not_expose_exception_or_credentials(self):
        self.record(cash())
        self.benchmark.side_effect = RuntimeError("credential-canary")
        with self.assertLogs("research", level="ERROR") as logs:
            response = self.load()
        self.assertEqual(response.status_code, 503)
        self.assertNotContains(response, "credential-canary", status_code=503)
        self.assertNotIn("credential-canary", " ".join(logs.output))

    def test_single_materialized_snapshot_needs_only_two_database_reads(self):
        self.invested()
        with self.assertNumQueries(2):
            result = load_daily_comparison(
                self.owner, self.portfolio.pk, DAY, END, "127.0.0.1", BENCHMARK_ID
            )
        self.assertIsNone(result[4].issue)

    def test_instrument_cap_preflight_precedes_benchmark_reference(self):
        self.invested()
        for sequence, identifier in enumerate(("sec_second", "sec_third"), start=3):
            self.reference.return_value = replace(
                REFERENCE, security=replace(REFERENCE.security, id=identifier)
            )
            self.record(
                trade(quantity="1", price="10", fees="0", sequence=sequence, security_id=identifier)
            )
        self.reference.reset_mock()
        self.assertEqual(self.load().status_code, 400)
        self.reference.assert_not_called()
        self.prices.assert_not_called()
        self.benchmark.assert_not_called()

    @override_settings(INTRINIO_API_KEY=TEST_KEY)
    def test_actual_transport_spends_at_most_ten_requests_including_benchmark(self):
        self.invested()
        self.reference.return_value = replace(
            REFERENCE, security=replace(REFERENCE.security, id="sec_second")
        )
        self.record(trade(quantity="1", price="10", fees="0", sequence=3, security_id="sec_second"))
        patch.stopall()
        _request_budget.reset()
        self.addCleanup(_request_budget.reset)
        calls = []
        days = (DAY, *(row.end_date for row in fixture_series(["100"] * 5).periods))

        def handler(request):
            calls.append(request)
            identifier = request.url.path.split("/")[2]
            security = {"id": identifier, "exchange_mic": "XNYS", "currency": "USD"}
            if not request.url.path.endswith("/prices"):
                return httpx.Response(200, json=security)
            page = int(request.url.params.get("next_page", "0"))
            selected = (
                days
                if identifier == BENCHMARK_ID
                else (days[page : page + 1] if page < 3 else days[3:])
            )
            return httpx.Response(
                200,
                json={
                    "security": security,
                    "stock_prices": [
                        {
                            "date": day.isoformat(),
                            "frequency": "daily",
                            "close": 10,
                            "adj_close": 10,
                            "intraperiod": False,
                        }
                        for day in selected
                    ],
                    "next_page": None if identifier == BENCHMARK_ID or page == 3 else str(page + 1),
                },
            )

        with patch(
            "research.services.IntrinioClient",
            side_effect=lambda key: IntrinioClient(key, transport=httpx.MockTransport(handler)),
        ):
            response = self.load()
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["comparison"].issue)
        self.assertEqual(len(calls), 10)
        self.assertEqual(_request_budget._total, 10)


class BenchmarkStorageGuardTests(SimpleTestCase):
    def test_sqlite_service_guard_precedes_all_market_data(self):
        from portfolios.services import PortfolioStorageUnavailable

        with (
            patch("portfolios.services.connection.vendor", "sqlite"),
            patch("research.services.security_details") as reference,
        ):
            with self.assertRaises(PortfolioStorageUnavailable):
                load_daily_comparison(None, uuid.uuid4(), DAY, END, "127.0.0.1", BENCHMARK_ID)
        reference.assert_not_called()
