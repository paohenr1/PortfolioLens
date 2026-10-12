"""Exercise the real adapter's one-page comparison ceiling and shared quota."""

from datetime import date
from unittest.mock import Mock, patch

import httpx
from django.test import SimpleTestCase, override_settings

from market_data.errors import CredentialsMissing, ProviderRateLimited
from market_data.intrinio import IntrinioClient
from research.services import _request_budget, _reserve_request, benchmark_prices
from tests.test_intrinio import TEST_KEY
from tests.test_prices import END, SECURITY_ID, START, observation, payload


class BenchmarkTransportTests(SimpleTestCase):
    def setUp(self):
        _request_budget.reset()
        self.addCleanup(_request_budget.reset)

    def test_remaining_cursor_is_incomplete_and_never_followed(self):
        calls = []
        reserve = Mock()

        def handler(request):
            calls.append(request)
            self.assertEqual(request.url.params["page_size"], "100")
            self.assertEqual(request.url.params["frequency"], "daily")
            return httpx.Response(200, json=payload([observation(START)], "more"))

        with IntrinioClient(TEST_KEY, transport=httpx.MockTransport(handler)) as provider:
            result = provider.benchmark_prices(SECURITY_ID, START, END, before_request=reserve)
        self.assertFalse(result.pagination_complete)
        self.assertEqual(len(calls), 1)
        reserve.assert_called_once()

    def test_invalid_or_long_range_fails_before_request_or_quota(self):
        handler, reserve = Mock(), Mock()
        with IntrinioClient(TEST_KEY, transport=httpx.MockTransport(handler)) as provider:
            for start, end in ((START, date(2020, 4, 1)), (END, START)):
                with self.assertRaises(ValueError):
                    provider.benchmark_prices(SECURITY_ID, start, end, before_request=reserve)
        handler.assert_not_called()
        reserve.assert_not_called()

    @override_settings(INTRINIO_API_KEY=TEST_KEY)
    def test_shared_budget_blocks_adapter_before_transport(self):
        for _ in range(10):
            _reserve_request("benchmark-address")
        handler = Mock()
        with patch(
            "research.services.IntrinioClient",
            side_effect=lambda key: IntrinioClient(key, transport=httpx.MockTransport(handler)),
        ):
            with self.assertRaises(ProviderRateLimited):
                benchmark_prices(SECURITY_ID, START, END, "benchmark-address")
        handler.assert_not_called()

    @override_settings(INTRINIO_API_KEY="")
    def test_missing_credentials_do_not_construct_client_or_spend_quota(self):
        with patch("research.services.IntrinioClient") as provider:
            with self.assertRaises(CredentialsMissing):
                benchmark_prices(SECURITY_ID, START, END, "benchmark-address")
        provider.assert_not_called()
        self.assertEqual(_request_budget._total, 0)
