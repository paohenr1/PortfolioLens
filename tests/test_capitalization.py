"""Independent dated-cap examples, source validation and shared quota boundaries."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from unittest.mock import patch

import httpx
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from market_data.capitalization import normalize_market_cap
from market_data.errors import (
    CompanyUnavailable,
    CredentialsMissing,
    InvalidResponse,
    MarketCapitalizationUnavailable,
    ProviderRateLimited,
)
from market_data.intrinio import IntrinioClient, normalize_security
from research.capitalization_views import MarketCapitalizationForm
from research.services import _request_budget, _reserve_request, market_capitalization
from tests.test_fundamentals import COMPANY, SECURITY
from tests.test_intrinio import TEST_KEY, fixture

CAP_DATE = date(2020, 1, 2)
TAG = {
    "tag": "marketcap",
    "name": "Market Capitalization",
    "unit": "usd",
    "statement_code": "calculations",
    "type": "valuation",
}


def cap_payload():
    # Invented exact financial example, never captured vendor data.
    return {
        "company": {"id": COMPANY, "name": "Fixture Research Corp", "ticker": "TSTF"},
        "historical_data": [{"date": "2020-01-02", "value": Decimal("3000000000000.125")}],
        "next_page": None,
    }


def cap_transport(request):
    if request.url.path == "/securities/" + SECURITY:
        return httpx.Response(200, json=fixture("security_reference.json"))
    if request.url.path == "/data_tags/marketcap":
        return httpx.Response(200, json=TAG)
    if request.url.path == f"/companies/{COMPANY}/historical_data/marketcap":
        payload = cap_payload()
        payload["historical_data"][0]["value"] = 3000000000000.125
        payload["historical_data"][0]["date"] = request.url.params["start_date"]
        return httpx.Response(200, json=payload)
    return httpx.Response(404)


class MarketCapNormalizationTests(SimpleTestCase):
    def result(self, payload=None, tag=None, security=None):
        return normalize_market_cap(
            payload if payload is not None else cap_payload(),
            TAG if tag is None else tag,
            security or normalize_security(fixture("security_reference.json")),
            CAP_DATE,
        )

    def test_exact_company_observation_retains_precision_and_separate_identity(self):
        result = self.result()
        self.assertEqual(result.value, Decimal("3000000000000.125"))
        self.assertEqual(result.company.id, COMPANY)
        self.assertEqual(result.security.id, SECURITY)
        self.assertEqual(result.valuation_date, CAP_DATE)
        self.assertEqual((result.unit, result.source_tag), ("usd", "marketcap"))
        self.assertTrue(result.observation_present and result.pagination_complete)
        self.assertIsNotNone(result.retrieved_at.utcoffset())

    def test_metric_currency_comes_from_tag_even_for_non_usd_listing(self):
        security = fixture("security_reference.json")
        security["currency"] = "EUR"
        self.assertEqual(self.result(security=normalize_security(security)).unit, "usd")

    def test_missing_date_null_value_and_observed_zero_remain_distinct(self):
        payload = cap_payload()
        payload["historical_data"] = []
        self.assertFalse(self.result(payload).observation_present)
        payload = cap_payload()
        payload["historical_data"][0]["value"] = None
        self.assertTrue(self.result(payload).observation_present)
        self.assertIsNone(self.result(payload).value)
        payload["historical_data"][0]["value"] = 0
        self.assertEqual(self.result(payload).value, Decimal(0))

    def test_partial_response_is_marked_without_following_cursor(self):
        payload = cap_payload()
        payload["next_page"] = "fixture_cursor"
        self.assertFalse(self.result(payload).pagination_complete)

    def test_absent_cursor_on_non_paged_response_does_not_invent_missing_data(self):
        payload = cap_payload()
        del payload["next_page"]
        self.assertTrue(self.result(payload).pagination_complete)

    def test_wrong_or_missing_tag_currency_scope_is_rejected(self):
        for key, value in (
            ("tag", "weightedavebasicsharesos"),
            ("unit", "shares"),
            ("unit", None),
            ("unit", "eur"),
            ("statement_code", "income_statement"),
            ("type", None),
        ):
            with self.subTest(key=key, value=value), self.assertRaises(InvalidResponse):
                self.result(tag={**TAG, key: value})

    def test_company_identity_must_match_listing_reference(self):
        for company in (None, [], {"id": "com_other"}, {}):
            payload = cap_payload()
            payload["company"] = company
            with self.subTest(company=company), self.assertRaises(InvalidResponse):
                self.result(payload)

    def test_malformed_or_unbounded_row_collections_rejected(self):
        for rows in (None, {}, [None], [[], []], [cap_payload()["historical_data"][0]] * 3):
            payload = cap_payload()
            payload["historical_data"] = rows
            with self.subTest(rows=rows), self.assertRaises(InvalidResponse):
                self.result(payload)

    def test_duplicate_exact_date_is_ambiguous_even_with_equal_values(self):
        payload = cap_payload()
        payload["historical_data"] *= 2
        with self.assertRaises(InvalidResponse):
            self.result(payload)

    def test_dates_must_match_exactly_without_prior_date_fallback(self):
        for raw_date in (
            None,
            20200102,
            "2020-01-01",
            "2020-1-2",
            "2020-02-30",
            "2020-01-02T00:00:00Z",
        ):
            payload = cap_payload()
            payload["historical_data"][0]["date"] = raw_date
            with self.subTest(raw_date=raw_date), self.assertRaises(InvalidResponse):
                self.result(payload)

    def test_values_must_be_bounded_nonnegative_json_numbers(self):
        for value in (
            True,
            "1",
            1.2,
            [],
            Decimal("NaN"),
            Decimal("sNaN"),
            Decimal("Infinity"),
            -1,
            Decimal("1e25"),
            Decimal("1e-19"),
            Decimal("0e-1000000"),
            Decimal("1.123456789012345678901234567890123456789012345"),
        ):
            payload = cap_payload()
            payload["historical_data"][0]["value"] = value
            with self.subTest(value=value), self.assertRaises(InvalidResponse):
                self.result(payload)

    def test_hostile_decimal_context_cannot_round_the_provider_value(self):
        with localcontext() as context:
            context.prec, context.Emax, context.Emin = 2, 1, -1
            for signal in context.traps:
                context.traps[signal] = True
            result = self.result()
        self.assertEqual(str(result.value), "3000000000000.125")

    def test_cursor_and_company_names_are_bounded_and_not_coerced(self):
        for cursor in ("", " ", 1, True, "a" * 1025, "a\nb"):
            payload = cap_payload()
            payload["next_page"] = cursor
            with self.subTest(cursor=cursor), self.assertRaises(InvalidResponse):
                self.result(payload)
        payload = cap_payload()
        payload["company"]["name"] = "x" * 513
        with self.assertRaises(InvalidResponse):
            self.result(payload)


class MarketCapAdapterTests(SimpleTestCase):
    def setUp(self):
        _request_budget.reset()
        self.addCleanup(_request_budget.reset)

    def test_three_fixed_backend_requests_reserve_quota_and_validate_metadata(self):
        requests, reservations = [], []

        def handler(request):
            requests.append(request)
            self.assertEqual(request.url.host, "api-v2.intrinio.com")
            self.assertEqual(request.url.scheme, "https")
            self.assertEqual(request.url.params["api_key"], TEST_KEY)
            return cap_transport(request)

        with IntrinioClient(TEST_KEY, transport=httpx.MockTransport(handler)) as c:
            result = c.market_capitalization(
                SECURITY, CAP_DATE, before_request=lambda: reservations.append(True)
            )
        self.assertEqual((len(requests), len(reservations)), (3, 3))
        self.assertEqual(requests[1].url.path, "/data_tags/marketcap")
        self.assertEqual(result.value, Decimal("3000000000000.125"))
        params = requests[-1].url.params
        self.assertEqual(params["start_date"], params["end_date"])
        self.assertEqual(params["start_date"], "2020-01-02")
        self.assertEqual(params["page_size"], "2")
        self.assertEqual(params["frequency"], "daily")
        self.assertNotIn("next_page", params)

    def test_invalid_ids_dates_fail_before_any_network_call(self):
        calls = []
        with IntrinioClient(
            TEST_KEY, transport=httpx.MockTransport(lambda r: calls.append(r))
        ) as c:
            for security_id, day in (
                ("../other", CAP_DATE),
                (SECURITY, datetime.now(UTC)),
                (SECURITY, date(1899, 1, 1)),
                (SECURITY, datetime.now(UTC).date() + timedelta(days=1)),
            ):
                with self.subTest(day=day), self.assertRaises(ValueError):
                    c.market_capitalization(security_id, day)
        self.assertEqual(calls, [])

    def test_missing_company_or_changed_instrument_stops_after_reference(self):
        for changes, error in (
            ({"company_id": None}, CompanyUnavailable),
            ({"id": "sec_other"}, InvalidResponse),
        ):
            calls = []

            def handler(request, calls=calls, changes=changes):
                calls.append(request)
                return httpx.Response(200, json={**fixture("security_reference.json"), **changes})

            with IntrinioClient(TEST_KEY, transport=httpx.MockTransport(handler)) as c:
                with self.assertRaises(error):
                    c.market_capitalization(SECURITY, CAP_DATE)
            self.assertEqual(len(calls), 1)

    def test_invalid_tag_stops_before_historical_request(self):
        calls = []

        def handler(request):
            calls.append(request)
            if request.url.path == "/data_tags/marketcap":
                return httpx.Response(200, json={**TAG, "unit": None})
            return cap_transport(request)

        with IntrinioClient(TEST_KEY, transport=httpx.MockTransport(handler)) as c:
            with self.assertRaises(InvalidResponse):
                c.market_capitalization(SECURITY, CAP_DATE)
        self.assertEqual(len(calls), 2)

    def test_rate_limit_on_each_stage_stops_without_retry_and_keeps_fixed_error(self):
        for failure_stage in range(1, 4):
            calls = []

            def handler(request, calls=calls, failure_stage=failure_stage):
                calls.append(request)
                if len(calls) == failure_stage:
                    return httpx.Response(429, text=TEST_KEY, headers={"Retry-After": "37"})
                return cap_transport(request)

            with IntrinioClient(TEST_KEY, transport=httpx.MockTransport(handler)) as c:
                with self.assertRaises(ProviderRateLimited) as caught:
                    c.market_capitalization(SECURITY, CAP_DATE)
            self.assertEqual(caught.exception.retry_after, 37)
            self.assertNotIn(TEST_KEY, str(caught.exception))
            self.assertEqual(len(calls), failure_stage)

    def test_history_404_has_company_metric_error_and_no_fallback(self):
        def handler(request):
            if "/historical_data/" in request.url.path:
                return httpx.Response(404)
            return cap_transport(request)

        with IntrinioClient(TEST_KEY, transport=httpx.MockTransport(handler)) as c:
            with self.assertRaises(MarketCapitalizationUnavailable):
                c.market_capitalization(SECURITY, CAP_DATE)

    def test_credential_echo_is_rejected_before_presentation(self):
        def handler(request):
            if "/historical_data/" in request.url.path:
                payload = cap_payload()
                payload["historical_data"] = []
                payload["company"]["name"] = TEST_KEY
                return httpx.Response(200, json=payload)
            return cap_transport(request)

        with IntrinioClient(TEST_KEY, transport=httpx.MockTransport(handler)) as c:
            with self.assertRaises(InvalidResponse):
                c.market_capitalization(SECURITY, CAP_DATE)

    @override_settings(INTRINIO_API_KEY=TEST_KEY)
    def test_existing_client_budget_can_stop_mid_load_without_extra_request(self):
        calls = []

        def handler(request):
            calls.append(request)
            return cap_transport(request)

        for _ in range(8):
            _reserve_request("cap-client")
        with patch(
            "research.services.IntrinioClient",
            side_effect=lambda key: IntrinioClient(key, transport=httpx.MockTransport(handler)),
        ):
            with self.assertRaises(ProviderRateLimited):
                market_capitalization(SECURITY, CAP_DATE, "cap-client")
        self.assertEqual(len(calls), 2)

    @override_settings(INTRINIO_API_KEY="")
    def test_missing_key_does_not_construct_provider(self):
        with patch("research.services.IntrinioClient") as provider:
            with self.assertRaises(CredentialsMissing):
                market_capitalization(SECURITY, CAP_DATE, "cap-client")
        provider.assert_not_called()


class MarketCapPageTests(SimpleTestCase):
    def setUp(self):
        self.url = reverse("market_capitalization", args=[SECURITY])

    def test_blank_form_no_io_and_no_store(self):
        with patch("research.capitalization_views.services.market_capitalization") as service:
            response = self.client.get(self.url)
        service.assert_not_called()
        self.assertContains(response, "No market data has been requested yet")
        self.assertNotContains(response, 'class="price-panel capitalization-panel"')
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_invalid_form_and_future_dates_no_io(self):
        for value in ("", "wrong", "1899-01-01", "9999-01-01"):
            with patch("research.capitalization_views.services.market_capitalization") as service:
                response = self.client.get(self.url, {"valuation_date": value})
            service.assert_not_called()
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertTrue(MarketCapitalizationForm({"valuation_date": CAP_DATE}).is_valid())

    def test_loaded_company_value_dates_source_scope_and_unknown_inputs_explicit(self):
        source = normalize_market_cap(
            cap_payload(), TAG, normalize_security(fixture("security_reference.json")), CAP_DATE
        )
        with patch(
            "research.capitalization_views.services.market_capitalization", return_value=source
        ) as service:
            response = self.client.get(self.url, {"valuation_date": "2020-01-02"})
        service.assert_called_once_with(SECURITY, CAP_DATE, "127.0.0.1")
        for text in (
            "3,000,000,000,000.125",
            "2020-01-02",
            COMPANY,
            "marketcap / usd",
            "Metric currency",
            "Underlying price date",
            "Underlying shares-outstanding count",
            "not supplied by this endpoint",
            "not verified",
            "historical-as-known",
            "Provider-reported company",
        ):
            self.assertContains(response, text)
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_missing_null_partial_values_and_zero_presentation(self):
        for mode, text in (
            ("missing", "No market capitalization observation"),
            ("null", "no market capitalization value"),
            ("partial", "response is incomplete"),
            ("zero", '<p class="metric-value">0</p>'),
        ):
            payload = cap_payload()
            if mode == "missing":
                payload["historical_data"] = []
            elif mode == "null":
                payload["historical_data"][0]["value"] = None
            elif mode == "partial":
                payload["next_page"] = "cursor"
            else:
                payload["historical_data"][0]["value"] = 0
            source = normalize_market_cap(
                payload, TAG, normalize_security(fixture("security_reference.json")), CAP_DATE
            )
            with patch(
                "research.capitalization_views.services.market_capitalization", return_value=source
            ):
                response = self.client.get(self.url, {"valuation_date": "2020-01-02"})
            self.assertContains(response, text)
            if mode != "zero":
                self.assertContains(response, '<p class="metric-value">Unavailable</p>')

    def test_provider_errors_hide_results_and_preserve_status_retry_and_no_store(self):
        for error in (
            ProviderRateLimited(37),
            InvalidResponse(),
            MarketCapitalizationUnavailable(),
            CredentialsMissing(),
        ):
            with patch(
                "research.capitalization_views.services.market_capitalization", side_effect=error
            ):
                response = self.client.get(self.url, {"valuation_date": "2020-01-02"})
            self.assertEqual(response.status_code, error.status)
            self.assertContains(response, error.message, status_code=error.status)
            self.assertNotContains(
                response, 'class="price-panel capitalization-panel"', status_code=error.status
            )
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            if error.retry_after:
                self.assertEqual(response.headers["Retry-After"], "37")

    def test_unexpected_failure_uses_generic_boundary_without_partial_value(self):
        with (
            patch(
                "research.capitalization_views.services.market_capitalization",
                side_effect=RuntimeError("synthetic internal failure"),
            ),
            self.assertLogs("research", level="ERROR"),
        ):
            response = self.client.get(self.url, {"valuation_date": "2020-01-02"})
        self.assertEqual(response.status_code, 503)
        self.assertNotContains(response, "synthetic internal failure", status_code=503)

    def test_company_name_is_escaped(self):
        payload = cap_payload()
        payload["company"]["name"] = '<script>alert("fixture")</script>'
        source = normalize_market_cap(
            payload, TAG, normalize_security(fixture("security_reference.json")), CAP_DATE
        )
        with patch(
            "research.capitalization_views.services.market_capitalization", return_value=source
        ):
            response = self.client.get(self.url, {"valuation_date": "2020-01-02"})
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, '<script>alert("fixture")</script>')

    def test_invalid_identifier_and_post_rejected_without_provider_io(self):
        with patch("research.capitalization_views.services.market_capitalization") as service:
            self.assertEqual(
                self.client.get(reverse("market_capitalization", args=["bad.id"])).status_code, 404
            )
            self.assertEqual(self.client.post(self.url).status_code, 405)
        service.assert_not_called()
