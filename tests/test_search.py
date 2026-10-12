from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import httpx
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from market_data.errors import ProviderRateLimited
from market_data.intrinio import IntrinioClient
from research.services import _request_budget, _reserve_request
from tests.test_intrinio import TEST_KEY, fixture


@override_settings(INTRINIO_API_KEY=TEST_KEY)
class SearchIntegrationTests(SimpleTestCase):
    def setUp(self):
        _request_budget.reset()
        self.addCleanup(_request_budget.reset)

    def provider(self, handler):
        return patch(
            "research.services.IntrinioClient",
            side_effect=lambda key: IntrinioClient(key, transport=httpx.MockTransport(handler)),
        )

    def test_search_then_select_resolves_the_provider_id(self):
        requests = []

        def handler(request):
            requests.append(request)
            if request.url.path == "/securities/search":
                return httpx.Response(200, json=fixture("security_search.json"))
            self.assertEqual(request.url.path, "/securities/sec_fixture_primary")
            return httpx.Response(200, json=fixture("security_reference.json"))

        with self.provider(handler):
            result = self.client.get(reverse("search"), {"q": "Fixture"})
            self.assertContains(result, "Fixture Research Corp")
            self.assertContains(result, "/stocks/sec_fixture_primary/")
            self.assertContains(result, "XNYS")
            self.assertContains(result, "XTST")
            self.assertContains(result, "Unavailable")
            self.assertContains(result, "Retrieved")
            details = self.client.get(reverse("security", args=["sec_fixture_primary"]))
        self.assertContains(details, "Listing details")
        self.assertContains(details, "USD")
        self.assertContains(details, "Active")
        self.assertContains(details, "2020-01-02")
        self.assertContains(details, "not a quote timestamp")
        self.assertEqual(details.headers["Cache-Control"], "no-store")
        self.assertEqual(len(requests), 2)
        self.assertNotContains(result, TEST_KEY)
        self.assertNotContains(details, TEST_KEY)

    def test_empty_search_does_not_contact_provider(self):
        with patch("research.services.IntrinioClient") as provider:
            response = self.client.get(reverse("search"))
        self.assertContains(response, "Start with a ticker or company name")
        provider.assert_not_called()

    def test_invalid_query_does_not_contact_provider(self):
        with patch("research.services.IntrinioClient") as provider:
            for query in ["", "   ", "x" * 101, "bad\x01query"]:
                with self.subTest(length=len(query)):
                    response = self.client.get(reverse("search"), {"q": query})
                    self.assertEqual(response.status_code, 400)
        provider.assert_not_called()

    def test_single_character_ticker_is_valid_and_whitespace_is_trimmed(self):
        def handler(request):
            self.assertEqual(request.url.params["query"], "F")
            return httpx.Response(200, json={"securities": []})

        with self.provider(handler):
            response = self.client.get(reverse("search"), {"q": " F "})
        self.assertContains(response, "No matching instruments")

    @override_settings(INTRINIO_API_KEY="")
    def test_unconfigured_search_and_detail_do_not_contact_provider(self):
        with patch("research.services.IntrinioClient") as provider:
            for url in [
                reverse("search") + "?q=TSTF",
                reverse("security", args=["sec_fixture_primary"]),
            ]:
                response = self.client.get(url)
                self.assertContains(response, "Intrinio is not configured.", status_code=503)
                self.assertNotContains(response, "No matching instruments", status_code=503)
        provider.assert_not_called()

    def test_provider_failures_are_safe_and_keep_the_search_form(self):
        for status, code, public_status in [
            (401, "authentication_failed", 503),
            (403, "entitlement_denied", 503),
            (429, "rate_limited", 429),
            (500, "unavailable", 503),
        ]:
            _request_budget.reset()
            with self.subTest(status=status):
                with self.provider(lambda r, status=status: httpx.Response(status, text=TEST_KEY)):
                    response = self.client.get(reverse("search"), {"q": "TSTF"})
                self.assertEqual(response.status_code, public_status)
                self.assertContains(
                    response, f'data-error-code="{code}"', status_code=public_status
                )
                self.assertContains(response, 'value="TSTF"', status_code=public_status)
                self.assertNotContains(response, TEST_KEY, status_code=public_status)
                if status == 429:
                    self.assertEqual(response.headers["Retry-After"], "60")

    def test_missing_instrument_has_a_real_404(self):
        with self.provider(lambda r: httpx.Response(404)):
            response = self.client.get(reverse("security", args=["sec_missing"]))
        self.assertContains(response, "not found in the available data feed", status_code=404)

    def test_search_endpoint_404_is_not_presented_as_no_matches(self):
        with self.provider(lambda r: httpx.Response(404)):
            response = self.client.get(reverse("search"), {"q": "TSTF"})
        self.assertContains(response, "temporarily unavailable", status_code=503)

    def test_invalid_identifier_is_rejected_before_provider_access(self):
        with patch("research.services.IntrinioClient") as provider:
            response = self.client.get(reverse("security", args=["invalid.identifier"]))
        self.assertEqual(response.status_code, 404)
        provider.assert_not_called()

    def test_provider_text_and_query_are_html_escaped(self):
        payload = {"securities": [{"id": "sec_escape", "name": "<script>alert(1)</script>"}]}
        with self.provider(lambda r: httpx.Response(200, json=payload)):
            response = self.client.get(reverse("search"), {"q": '<img src=x onerror="alert(1)">'})
        self.assertNotContains(response, "<script>")
        self.assertNotContains(response, "<img src=x")
        self.assertContains(response, "&lt;script&gt;")

    def test_malformed_data_is_not_rendered_as_valid_results(self):
        with self.provider(lambda r: httpx.Response(200, json={"securities": [None]})):
            response = self.client.get(reverse("search"), {"q": "TSTF"})
        self.assertContains(response, 'data-error-code="invalid_response"', status_code=503)

    def test_credential_echo_in_a_valid_record_is_never_rendered(self):
        payload = {"securities": [{"id": "sec_echo", "name": TEST_KEY}]}
        with self.provider(lambda r: httpx.Response(200, json=payload)):
            response = self.client.get(reverse("search"), {"q": "TSTF"})
        self.assertContains(response, 'data-error-code="invalid_response"', status_code=503)
        self.assertNotContains(response, TEST_KEY, status_code=503)

    def test_unexpected_error_has_redacted_diagnostics_and_a_safe_page(self):
        with patch("research.services.search_securities", side_effect=RuntimeError(TEST_KEY)):
            with self.assertLogs("research", level="ERROR") as logs:
                response = self.client.get(reverse("search"), {"q": "TSTF"})
        self.assertNotContains(response, TEST_KEY, status_code=503)
        self.assertNotIn(TEST_KEY, "\n".join(logs.output))
        self.assertIn("[REDACTED]", "\n".join(logs.output))

    def test_post_and_head_do_not_spend_provider_quota(self):
        with patch("research.services.IntrinioClient") as provider:
            self.assertEqual(self.client.post(reverse("search"), {"q": "TSTF"}).status_code, 405)
            self.assertEqual(self.client.head(reverse("search") + "?q=TSTF").status_code, 405)
        provider.assert_not_called()

    def test_client_limit_prevents_additional_upstream_requests(self):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={"securities": []})

        with self.provider(handler):
            for _ in range(10):
                self.assertEqual(self.client.get(reverse("search"), {"q": "TSTF"}).status_code, 200)
            response = self.client.get(reverse("search"), {"q": "TSTF"})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(len(requests), 10)


class BudgetTests(SimpleTestCase):
    def setUp(self):
        _request_budget.reset()
        self.addCleanup(_request_budget.reset)

    @patch("research.services.time.monotonic", return_value=120.0)
    def test_global_limit_survives_cache_clear_and_unique_client_flood(self, clock):
        from django.core.cache import cache

        for number in range(30):
            _reserve_request(f"client-{number}")
        cache.clear()
        for number in range(1000):
            with self.assertRaises(ProviderRateLimited):
                _reserve_request(f"another-client-{number}")

    @patch("research.services.time.monotonic", return_value=120.0)
    def test_concurrent_requests_cannot_bypass_the_client_counter(self, clock):
        def reserve(number):
            try:
                _reserve_request("one-client")
                return True
            except ProviderRateLimited:
                return False

        with ThreadPoolExecutor(max_workers=8) as executor:
            allowed = list(executor.map(reserve, range(30)))
        self.assertEqual(sum(allowed), 10)

    def test_new_window_restores_budget(self):
        with patch("research.services.time.monotonic", return_value=120.0):
            for _ in range(10):
                _reserve_request("one-client")
        with patch("research.services.time.monotonic", return_value=180.0):
            _reserve_request("one-client")
