import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path

import httpx
from django.test import SimpleTestCase, override_settings

from market_data.errors import (
    AuthenticationFailed,
    CredentialsMissing,
    EntitlementDenied,
    InstrumentNotFound,
    InvalidResponse,
    ProviderError,
    ProviderRateLimited,
)
from market_data.intrinio import MAX_RESPONSE_BYTES, IntrinioClient

FIXTURES = Path(__file__).parent / "fixtures"
TEST_KEY = "test-only key+&=/not-real"


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


class IntrinioTests(SimpleTestCase):
    def provider_client(self, handler):
        return IntrinioClient(TEST_KEY, transport=httpx.MockTransport(handler))

    def test_search_uses_backend_key_and_one_bounded_request(self):
        requests = []

        def handler(request):
            requests.append(request)
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.url.host, "api-v2.intrinio.com")
            self.assertEqual(request.url.scheme, "https")
            self.assertEqual(request.url.path, "/securities/search")
            self.assertEqual(request.url.params["api_key"], TEST_KEY)
            self.assertEqual(request.url.params["query"], "Fixture Research")
            self.assertEqual(request.url.params["page_size"], "20")
            return httpx.Response(200, json=fixture("security_search.json"))

        with self.provider_client(handler) as client:
            result = client.search("Fixture Research")
        self.assertEqual(len(requests), 1)
        self.assertEqual(len(result.securities), 2)
        self.assertEqual(result.securities[0].exchange_mic, "XNYS")
        self.assertEqual(result.securities[1].exchange_mic, "XTST")
        self.assertIsNone(result.securities[1].currency)
        self.assertEqual(result.retrieved_at.tzinfo, UTC)

    def test_empty_results_are_a_valid_observation(self):
        with self.provider_client(
            lambda request: httpx.Response(200, json={"securities": []})
        ) as client:
            self.assertEqual(client.search("Unknown").securities, ())

    def test_detail_uses_id_and_preserves_date_only_metadata(self):
        def handler(request):
            self.assertEqual(request.url.path, "/securities/sec_fixture_primary")
            return httpx.Response(200, json=fixture("security_reference.json"))

        with self.provider_client(handler) as client:
            result = client.security("sec_fixture_primary")
        self.assertEqual(result.security.last_stock_price_date.isoformat(), "2020-01-02")
        self.assertEqual(result.security.exchange_mic, "XNYS")
        self.assertTrue(result.security.active)
        self.assertFalse(result.security.delisted)

    def test_missing_optional_fields_remain_missing(self):
        with self.provider_client(
            lambda request: httpx.Response(200, json={"id": "sec_minimal"})
        ) as client:
            result = client.security("sec_minimal")
        self.assertIsNone(result.security.currency)
        self.assertIsNone(result.security.ticker)
        self.assertIsNone(result.security.active)
        self.assertIsNone(result.security.last_stock_price_date)

    def test_wrong_detail_identity_is_rejected(self):
        with self.provider_client(
            lambda request: httpx.Response(200, json={"id": "sec_other"})
        ) as client:
            with self.assertRaises(InvalidResponse):
                client.security("sec_requested")

    def test_invalid_identifiers_never_make_a_request(self):
        def handler(request):
            self.fail("An invalid identifier must not reach the transport")

        with self.provider_client(handler) as client:
            for identifier in ["", "../other", "https://other.example", "a/b", "x" * 101]:
                with self.subTest(identifier=identifier), self.assertRaises(ValueError):
                    client.security(identifier)

    def test_invalid_queries_never_make_a_request(self):
        with self.provider_client(lambda request: self.fail("Unexpected request")) as client:
            for query in ["", "   ", "x" * 101]:
                with self.subTest(length=len(query)), self.assertRaises(ValueError):
                    client.search(query)

    def test_missing_key_is_rejected_before_creating_transport(self):
        with self.assertRaises(CredentialsMissing):
            IntrinioClient(" ")

    def test_provider_errors_do_not_expose_error_bodies_or_authenticated_urls(self):
        cases = [
            (401, AuthenticationFailed),
            (403, EntitlementDenied),
            (404, InstrumentNotFound),
            (429, ProviderRateLimited),
            (500, ProviderError),
            (302, ProviderError),
        ]
        for status, expected in cases:
            with self.subTest(status=status):
                requests = []

                def handler(request, status=status, requests=requests):
                    requests.append(request)
                    return httpx.Response(
                        status, text=TEST_KEY, headers={"Location": "https://untrusted.example"}
                    )

                with self.provider_client(handler) as client, self.assertRaises(expected) as raised:
                    client.search("TSTF")
                self.assertNotIn(TEST_KEY, str(raised.exception))
                self.assertNotIn("api_key=", str(raised.exception))
                self.assertEqual(len(requests), 1)

    def test_timeout_is_safe_and_not_retried(self):
        requests = []

        def handler(request):
            requests.append(request)
            raise httpx.ReadTimeout(str(request.url), request=request)

        with self.provider_client(handler) as client, self.assertRaises(ProviderError) as raised:
            client.search("TSTF")
        self.assertNotIn(TEST_KEY, str(raised.exception))
        self.assertTrue(raised.exception.__suppress_context__)
        self.assertEqual(len(requests), 1)

    def test_retry_after_is_bounded_and_accepts_http_dates(self):
        cases = [("120", 120), ("999999", 3600), ("-10", 1), ("invalid", 60)]
        for header, expected in cases:
            with self.subTest(header=header):
                with self.provider_client(
                    lambda r, header=header: httpx.Response(429, headers={"Retry-After": header})
                ) as c:
                    with self.assertRaises(ProviderRateLimited) as raised:
                        c.search("TSTF")
                self.assertEqual(raised.exception.retry_after, expected)
        timestamp = format_datetime(datetime.now(UTC) + timedelta(seconds=125), usegmt=True)
        with self.provider_client(
            lambda r: httpx.Response(429, headers={"Retry-After": timestamp})
        ) as c:
            with self.assertRaises(ProviderRateLimited) as raised:
                c.search("TSTF")
        self.assertGreaterEqual(raised.exception.retry_after, 120)
        self.assertLessEqual(raised.exception.retry_after, 125)

    def test_malformed_json_duplicate_fields_and_nonfinite_numbers_fail(self):
        for body in [
            b"<html>error</html>",
            b'{"securities": [], "securities": []}',
            b'{"securities": [], "extra": NaN}',
            b"\xff",
        ]:
            with self.subTest(body=body):
                with self.provider_client(
                    lambda request, body=body: httpx.Response(200, content=body)
                ) as client:
                    with self.assertRaises(InvalidResponse):
                        client.search("TSTF")

    def test_wrong_response_shapes_and_records_fail(self):
        payloads = [
            [],
            {},
            {"securities": None},
            {"securities": {}},
            {"securities": [{"id": "sec_one"}] * 21},
            {"securities": [{"id": "sec_one"}] * 2},
            {"securities": [{"name": "Missing identity"}]},
            {"securities": [{"id": "sec_one", "active": 1}]},
            {"securities": [{"id": "sec_one", "currency": "unknown"}]},
            {"securities": [{"id": "sec_one", "last_stock_price": "2020-02-30"}]},
            {"securities": [{"id": "sec_one", "name": 42}]},
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                with self.provider_client(
                    lambda request, payload=payload: httpx.Response(200, json=payload)
                ) as client:
                    with self.assertRaises(InvalidResponse):
                        client.search("TSTF")

    def test_response_size_is_bounded(self):
        body = b" " * (MAX_RESPONSE_BYTES + 1)
        with self.provider_client(lambda request: httpx.Response(200, content=body)) as client:
            with self.assertRaises(InvalidResponse):
                client.search("TSTF")

    @override_settings(INTRINIO_API_KEY=TEST_KEY)
    def test_httpx_diagnostic_logging_redacts_raw_and_encoded_keys(self):
        with self.assertLogs("httpx", level="INFO") as logs:
            with self.provider_client(
                lambda request: httpx.Response(200, json={"securities": []})
            ) as client:
                client.search("TSTF")
        output = "\n".join(logs.output)
        self.assertIn("[REDACTED]", output)
        self.assertNotIn(TEST_KEY, output)
        self.assertNotIn("test-only+key", output)
