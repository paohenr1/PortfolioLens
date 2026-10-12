"""Risk reuses the existing price transport, validation, quotas and safe boundary."""

from datetime import date
from unittest.mock import patch

import httpx
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from market_data.intrinio import IntrinioClient
from research.services import _request_budget, _reserve_request
from tests.test_intrinio import TEST_KEY
from tests.test_prices import observation, payload
from tests.test_stock_risk import stock_history


@override_settings(INTRINIO_API_KEY=TEST_KEY)
class StockRiskPageTests(SimpleTestCase):
    def setUp(self):
        _request_budget.reset()
        self.addCleanup(_request_budget.reset)
        self.url = reverse("prices", args=["sec_fixture_primary"])
        self.query = {"start_date": "2020-01-02", "end_date": "2020-01-06", "basis": "raw"}

    def provider(self, handler):
        return patch(
            "research.services.IntrinioClient",
            side_effect=lambda key: IntrinioClient(key, transport=httpx.MockTransport(handler)),
        )

    def data(self):
        return payload(
            [
                observation(date(2020, 1, 2), close=100, adjusted=50),
                observation(date(2020, 1, 3), close=50, adjusted=50),
                observation(date(2020, 1, 6), close=55, adjusted=55),
            ]
        )

    def test_price_form_does_not_load_risk_or_call_provider_before_submission(self):
        with patch("research.services.IntrinioClient") as provider:
            response = self.client.get(self.url)
            invalid = self.client.get(self.url, {**self.query, "basis": "auto"})
        provider.assert_not_called()
        self.assertNotContains(response, "Stock volatility and drawdown")
        self.assertNotContains(invalid, "Stock volatility and drawdown", status_code=400)

    def test_same_single_price_request_renders_correct_basis_stats_and_two_charts(self):
        calls = []

        def handler(request):
            calls.append(request.url.path)
            return httpx.Response(200, json=self.data())

        with self.provider(handler):
            raw = self.client.get(self.url, self.query)
            adjusted = self.client.get(self.url, {**self.query, "basis": "adjusted"})
        self.assertEqual(calls, ["/securities/sec_fixture_primary/prices"] * 2)
        self.assertContains(raw, "Stock volatility and drawdown")
        self.assertEqual(str(raw.context["stock_risk"].maximum_drawdown_percent), "50.0000")
        self.assertEqual(str(adjusted.context["stock_risk"].maximum_drawdown_percent), "0.0000")
        self.assertContains(adjusted, "7.0711%")
        self.assertContains(raw, "Corporate actions can create apparent losses")
        self.assertContains(adjusted, "adjustment method is not independently reconstructed")
        self.assertContains(raw, 'class="price-chart"', count=2)
        self.assertContains(raw, "research/prices.js", count=1)
        self.assertContains(raw, 'tabindex="0" role="img"')
        self.assertContains(raw, "sample standard deviation")
        self.assertContains(raw, "252-session scaling is an assumption")
        self.assertContains(adjusted, "not a portfolio total-return calculation")
        self.assertContains(raw, "Retrieved 202")
        self.assertNotContains(raw, TEST_KEY)
        self.assertEqual(raw.headers["Cache-Control"], "no-store")

    def test_gaps_withhold_stats_but_keep_supplied_price_chart_and_table(self):
        data = self.data()
        data["stock_prices"].pop(1)
        with self.provider(lambda r: httpx.Response(200, json=data)):
            response = self.client.get(self.url, self.query)
        self.assertContains(response, "Missing, extra, duplicate or unordered dates")
        self.assertContains(response, 'class="price-chart"', count=1)
        self.assertContains(response, "View observations table (2)")
        self.assertNotContains(response, "stock-risk-table")
        self.assertIsNone(response.context["stock_risk"].daily_volatility_percent)

    def test_partial_paging_consumes_only_existing_four_requests_and_withholds_risk(self):
        calls = []

        def handler(request):
            calls.append(request)
            day = (2, 3, 6, 7)[len(calls) - 1]
            return httpx.Response(
                200, json=payload([observation(date(2020, 1, day))], f"page-{len(calls)}")
            )

        with self.provider(handler):
            response = self.client.get(self.url, {**self.query, "end_date": "2020-01-08"})
        self.assertEqual(len(calls), 4)
        self.assertContains(response, "Partial history")
        self.assertContains(response, "complete, verified historical-price response")
        self.assertIsNone(response.context["stock_drawdown_chart"])

    def test_unsupported_exchange_and_today_leave_price_workflow_available(self):
        data = self.data()
        data["security"]["exchange_mic"] = "XLON"
        with self.provider(lambda r: httpx.Response(200, json=data)):
            response = self.client.get(self.url, self.query)
        self.assertContains(response, "only identified U.S. equity venues")
        self.assertContains(response, 'class="price-chart"', count=1)

    def test_unknown_currency_is_not_assumed_to_be_usd_for_dimensionless_risk(self):
        data = self.data()
        data["security"]["currency"] = None
        with self.provider(lambda r: httpx.Response(200, json=data)):
            response = self.client.get(self.url, self.query)
        self.assertContains(response, "50.0000%")
        self.assertContains(response, "Unavailable — no currency assumed")
        self.assertNotContains(response, "USD")

    def test_existing_quota_and_provider_errors_clear_both_charts_and_risk(self):
        for _ in range(9):
            _reserve_request("127.0.0.1")
        calls = []
        with self.provider(lambda r: calls.append(r) or httpx.Response(200, json=self.data())):
            self.assertEqual(self.client.get(self.url, self.query).status_code, 200)
            limited = self.client.get(self.url, self.query)
        self.assertEqual(len(calls), 1)
        self.assertEqual(limited.status_code, 429)
        self.assertNotContains(limited, "Stock volatility and drawdown", status_code=429)
        for status, expected in ((403, 503), (429, 429), (500, 503)):
            _request_budget.reset()
            with self.provider(
                lambda r, status=status: httpx.Response(
                    status, text=TEST_KEY, headers={"Retry-After": "60"}
                )
            ):
                response = self.client.get(self.url, self.query)
            self.assertNotContains(response, 'class="price-chart"', status_code=expected)
            self.assertNotContains(response, "Stock volatility and drawdown", status_code=expected)
            self.assertNotContains(response, TEST_KEY, status_code=expected)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            if status == 429:
                self.assertEqual(response.headers["Retry-After"], "60")

    def test_unexpected_calculation_failure_keeps_all_context_redacted(self):
        with patch("research.views.calculate_stock_risk", side_effect=RuntimeError(TEST_KEY)):
            with patch("research.services.historical_prices", return_value=stock_history()):
                with self.assertLogs("research", level="ERROR") as logs:
                    response = self.client.get(self.url, self.query)
        self.assertNotContains(response, TEST_KEY, status_code=503)
        self.assertNotContains(response, "Stock volatility and drawdown", status_code=503)
        self.assertNotIn(TEST_KEY, "\n".join(logs.output))
        self.assertNotIn("history", response.context)

    def test_unconfirmed_missing_and_zero_closes_do_not_create_risk_series(self):
        for change in (
            {"adj_close": None},
            {"adj_close": 0},
            {"intraperiod": None},
            {"intraperiod": True},
        ):
            data = self.data()
            data["stock_prices"][1].update(change)
            with self.provider(lambda r, data=data: httpx.Response(200, json=data)):
                response = self.client.get(self.url, {**self.query, "basis": "adjusted"})
            self.assertContains(response, "strictly positive selected close")
            self.assertIsNone(response.context["stock_drawdown_chart"])

    def test_annualized_statistics_and_source_dates_render_after_twenty_returns(self):
        history = stock_history(["100", "200"] * 10 + ["100"])
        with patch("research.services.historical_prices", return_value=history) as service:
            response = self.client.get(
                self.url, {**self.query, "end_date": history.end_date.isoformat()}
            )
        service.assert_called_once()
        self.assertContains(response, "1221.5176%")
        self.assertContains(response, "2020-03-01 00:00:00 UTC")
        self.assertContains(response, "21 validated closes")
