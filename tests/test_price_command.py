from io import StringIO
from unittest.mock import patch

import httpx
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from market_data.intrinio import IntrinioClient
from research.services import _request_budget
from tests.test_intrinio import TEST_KEY, fixture


@override_settings(INTRINIO_API_KEY=TEST_KEY)
class PriceCommandTests(SimpleTestCase):
    def setUp(self):
        _request_budget.reset()
        self.addCleanup(_request_budget.reset)

    def run_command(self, **kwargs):
        output = StringIO()
        call_command(
            "verify_prices",
            start_date="2020-01-01",
            end_date="2020-01-31",
            stdout=output,
            **kwargs,
        )
        return output.getvalue()

    def provider(self, handler):
        return patch(
            "research.services.IntrinioClient",
            side_effect=lambda key: IntrinioClient(key, transport=httpx.MockTransport(handler)),
        )

    def test_mock_workflow_counts_completed_closes_and_keeps_other_claims_unverified(self):
        requests = []

        def handler(request):
            requests.append(request)
            name = (
                "security_search.json"
                if request.url.path.endswith("search")
                else "daily_prices.json"
            )
            return httpx.Response(200, json=fixture(name))

        with self.provider(handler):
            output = self.run_command()
        self.assertIn("4 completed adjusted close observations", output)
        self.assertIn(
            "Fundamentals, real-time access, wider coverage, and licensing remain unverified",
            output,
        )
        self.assertNotIn(TEST_KEY, output)
        self.assertEqual(len(requests), 2)

    @override_settings(INTRINIO_API_KEY="")
    def test_missing_key_cannot_report_success(self):
        with patch("research.services.IntrinioClient") as provider:
            with self.assertRaisesMessage(CommandError, "not configured"):
                self.run_command()
        provider.assert_not_called()

    def test_invalid_query_or_dates_do_not_spend_quota(self):
        with patch("research.services.IntrinioClient") as provider:
            for options in [
                {"query": ""},
                {"start_date": "bad"},
                {"start_date": "2020-01-01", "end_date": "2022-01-01"},
            ]:
                with self.assertRaises(CommandError):
                    call_command("verify_prices", stdout=StringIO(), **options)
        provider.assert_not_called()

    def test_empty_denied_or_missing_closes_fail_acceptance(self):
        for case in ["empty_search", "empty_prices", "denied", "missing"]:

            def handler(request, case=case):
                if request.url.path.endswith("search"):
                    search = fixture("security_search.json")
                    if case == "empty_search":
                        search["securities"] = []
                    return httpx.Response(200, json=search)
                if case == "denied":
                    return httpx.Response(403, text=TEST_KEY)
                prices = fixture("daily_prices.json")
                if case == "empty_prices":
                    prices["stock_prices"] = []
                if case == "missing":
                    for row in prices["stock_prices"]:
                        row["adj_close"] = None
                return httpx.Response(200, json=prices)

            _request_budget.reset()
            with self.subTest(case=case), self.provider(handler):
                with self.assertRaises(CommandError):
                    self.run_command()
