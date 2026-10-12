"""Single-request daily prices exercise the actual HTTPX adapter and shared quota."""

from unittest.mock import patch

import httpx
from django.test import SimpleTestCase, override_settings

from market_data.errors import CredentialsMissing, ProviderRateLimited
from market_data.intrinio import IntrinioClient
from research.services import _request_budget, _reserve_request, daily_prices
from tests.test_intrinio import TEST_KEY
from tests.test_prices import observation, payload
from tests.test_valuation import AS_OF, IDENTIFIER


@override_settings(INTRINIO_API_KEY=TEST_KEY)
class DailyQuoteProviderTests(SimpleTestCase):
    def setUp(self):
        _request_budget.reset()
        self.addCleanup(_request_budget.reset)

    def test_exact_date_daily_frequency_and_one_page_even_with_cursor(self):
        calls = []

        def handler(request):
            calls.append(request)
            self.assertEqual(request.url.path, f"/securities/{IDENTIFIER}/prices")
            self.assertEqual(request.url.params["start_date"], AS_OF.isoformat())
            self.assertEqual(request.url.params["end_date"], AS_OF.isoformat())
            self.assertEqual(request.url.params["frequency"], "daily")
            self.assertNotIn("next_page", request.url.params)
            return httpx.Response(200, json=payload([observation(AS_OF)], "more"))

        with IntrinioClient(TEST_KEY, transport=httpx.MockTransport(handler)) as provider:
            result = provider.daily_prices(IDENTIFIER, AS_OF)
        self.assertEqual(len(calls), 1)
        self.assertFalse(result.pagination_complete)

    @override_settings(INTRINIO_API_KEY="")
    def test_missing_key_spends_no_quota_and_opens_no_transport(self):
        with patch("research.services.IntrinioClient") as provider:
            with self.assertRaises(CredentialsMissing):
                daily_prices(IDENTIFIER, AS_OF, "127.0.0.1")
        provider.assert_not_called()
        self.assertEqual(_request_budget._total, 0)

    def test_daily_price_requests_share_reference_and_history_budget(self):
        calls = []
        for _ in range(10):
            _reserve_request("127.0.0.1")
        with patch(
            "research.services.IntrinioClient",
            side_effect=lambda key: IntrinioClient(
                key, transport=httpx.MockTransport(lambda r: calls.append(r))
            ),
        ):
            with self.assertRaises(ProviderRateLimited):
                daily_prices(IDENTIFIER, AS_OF, "127.0.0.1")
        self.assertEqual(calls, [])
