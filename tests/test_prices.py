import copy
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import httpx
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from market_data.contracts import DailyPrice, PriceHistory, Security
from market_data.errors import InvalidResponse, ProviderRateLimited
from market_data.intrinio import IntrinioClient
from market_data.prices import MAX_PRICE_PAGES, validate_price_range
from research.charts import build_price_chart
from research.services import _request_budget, _reserve_request
from tests.test_intrinio import TEST_KEY, fixture

START = date(2020, 1, 1)
END = date(2020, 1, 31)
SECURITY_ID = "sec_fixture_primary"


def observation(day, close=10, adjusted=9, intraperiod=False):
    return {
        "date": day.isoformat(),
        "frequency": "daily",
        "intraperiod": intraperiod,
        "close": close,
        "adj_close": adjusted,
    }


def payload(items, next_page=None):
    return {
        "security": fixture("daily_prices.json")["security"],
        "stock_prices": items,
        "next_page": next_page,
    }


class HistoricalAdapterTests(SimpleTestCase):
    def provider(self, handler):
        return IntrinioClient(TEST_KEY, transport=httpx.MockTransport(handler))

    def test_request_dates_identity_frequency_and_chronological_decimal_values(self):
        requests = []

        def handler(request):
            requests.append(request)
            self.assertEqual(request.url.path, "/securities/sec_fixture_primary/prices")
            self.assertEqual(request.url.params["start_date"], "2020-01-01")
            self.assertEqual(request.url.params["end_date"], "2020-01-31")
            self.assertEqual(request.url.params["frequency"], "daily")
            self.assertEqual(request.url.params["page_size"], "100")
            self.assertEqual(request.url.params["api_key"], TEST_KEY)
            return httpx.Response(200, json=fixture("daily_prices.json"))

        with self.provider(handler) as provider:
            result = provider.price_history(SECURITY_ID, START, END)
        self.assertEqual(len(requests), 1)
        self.assertEqual(result.observations[0].date, date(2020, 1, 2))
        self.assertEqual(result.observations[0].close, Decimal("10.5"))
        self.assertIsNone(result.observations[3].adjusted_close)
        self.assertTrue(result.observations[-2].intraperiod)
        self.assertIsNone(result.observations[-1].intraperiod)
        self.assertEqual(result.security.currency, "USD")
        self.assertEqual(result.retrieved_at.tzinfo, UTC)
        self.assertTrue(result.pagination_complete)

    def test_numeric_json_precision_is_preserved(self):
        text = json.dumps(payload([observation(START)])).replace(
            '"close": 10', '"close": 100.123456789012345678'
        )
        with self.provider(lambda r: httpx.Response(200, content=text)) as provider:
            result = provider.price_history(SECURITY_ID, START, END)
        self.assertEqual(result.observations[0].close, Decimal("100.123456789012345678"))

    def test_extreme_json_exponents_and_nonfinite_prices_cannot_expand_html(self):
        text = json.dumps(payload([observation(START)]))
        for number in ["0e999999", "1e999999", "1e-999999", "NaN", "Infinity"]:
            case = text.replace('"close": 10', '"close": ' + number)
            with (
                self.subTest(number=number),
                self.provider(lambda r, case=case: httpx.Response(200, content=case)) as provider,
            ):
                with self.assertRaises(InvalidResponse):
                    provider.price_history(SECURITY_ID, START, END)

    def test_pages_keep_dates_and_opaque_token_and_reserve_each_request(self):
        requests, reservations = [], []

        def handler(request):
            requests.append(request)
            if len(requests) == 1:
                self.assertNotIn("next_page", request.url.params)
                return httpx.Response(200, json=payload([observation(END)], "opaque+/=& token"))
            self.assertEqual(request.url.params["next_page"], "opaque+/=& token")
            self.assertEqual(request.url.params["start_date"], START.isoformat())
            return httpx.Response(200, json=payload([observation(START)]))

        with self.provider(handler) as provider:
            result = provider.price_history(
                SECURITY_ID, START, END, before_request=lambda: reservations.append(True)
            )
        self.assertEqual([row.date for row in result.observations], [START, END])
        self.assertEqual(len(requests), len(reservations))
        self.assertEqual(len(requests), 2)

    def test_pagination_cap_returns_explicit_partial_history(self):
        requests = []

        def handler(request):
            requests.append(request)
            index = len(requests)
            return httpx.Response(
                200, json=payload([observation(START + timedelta(days=index))], f"page-{index}")
            )

        with self.provider(handler) as provider:
            result = provider.price_history(SECURITY_ID, START, END)
        self.assertFalse(result.pagination_complete)
        self.assertEqual(len(requests), MAX_PRICE_PAGES)
        self.assertEqual(len(result.observations), MAX_PRICE_PAGES)

    def test_invalid_range_and_identifier_never_reach_transport(self):
        cases = [
            (SECURITY_ID, END, START),
            (SECURITY_ID, date(2020, 1, 1), date(2021, 1, 1)),
            (SECURITY_ID, START, datetime.now(UTC).date() + timedelta(days=1)),
            (SECURITY_ID, date(1899, 12, 31), START),
            (SECURITY_ID, datetime(2020, 1, 1), END),
            ("bad.identifier", START, END),
        ]
        with self.provider(lambda r: self.fail("Invalid inputs must not spend quota")) as provider:
            for identifier, start, end in cases:
                with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                    provider.price_history(identifier, start, end)
        validate_price_range(START, START)
        validate_price_range(date(2020, 1, 1), date(2020, 12, 31))

    def test_empty_history_is_valid_but_not_fabricated(self):
        with self.provider(lambda r: httpx.Response(200, json=payload([]))) as provider:
            result = provider.price_history(SECURITY_ID, START, END)
        self.assertEqual(result.observations, ())
        self.assertTrue(result.pagination_complete)

    def test_invalid_record_types_prices_and_dates_are_rejected(self):
        mutations = [
            ("date", "20200102"),
            ("date", "2020-02-30"),
            ("date", "2019-12-31"),
            ("date", "2020-02-01"),
            ("frequency", "weekly"),
            ("frequency", None),
            ("intraperiod", 0),
            ("close", True),
            ("close", "10.5"),
            ("close", -1),
            ("close", 1e13),
            ("close", 1e-19),
            ("close", []),
            ("adj_close", "invalid"),
        ]
        for key, value in mutations:
            record = observation(START)
            record[key] = value
            with self.subTest(key=key, value=value):
                with (
                    self.provider(
                        lambda r, record=record: httpx.Response(200, json=payload([record]))
                    ) as provider,
                    self.assertRaises(InvalidResponse),
                ):
                    provider.price_history(SECURITY_ID, START, END)

    def test_zero_and_absent_close_fields_are_distinct(self):
        item = observation(START, close=0, adjusted=None)
        with self.provider(lambda r: httpx.Response(200, json=payload([item]))) as provider:
            result = provider.price_history(SECURITY_ID, START, END)
        self.assertEqual(result.observations[0].close, Decimal(0))
        self.assertIsNone(result.observations[0].adjusted_close)

    def test_ambiguous_identity_cursor_and_duplicate_records_are_rejected(self):
        base = payload([observation(START)])
        cases = [
            {**base, "security": {"id": "sec_wrong"}},
            {**base, "security": None},
            {**base, "stock_prices": None},
            {**base, "stock_prices": [None]},
            {**base, "next_page": ""},
            {**base, "next_page": "x" * 1025},
            {**base, "next_page": "bad\n"},
            {**base, "next_page": 123},
            {**base, "stock_prices": [observation(START)] * 101},
            {**base, "stock_prices": [observation(START)] * 2},
            {**base, "stock_prices": [], "next_page": "cursor"},
            {k: v for k, v in base.items() if k != "next_page"},
        ]
        for case in cases:
            with self.subTest(case=cases.index(case)):
                with self.provider(lambda r, case=case: httpx.Response(200, json=case)) as provider:
                    with self.assertRaises(InvalidResponse):
                        provider.price_history(SECURITY_ID, START, END)

    def test_cross_page_duplicate_dates_currency_venue_change_and_cursor_cycles_fail(self):
        for issue in ["duplicate", "currency", "venue", "cursor"]:
            requests = []

            def handler(request, issue=issue, requests=requests):
                requests.append(request)
                index = len(requests)
                day = START if issue == "duplicate" else START + timedelta(days=index)
                page = payload(
                    [observation(day)], "token" if index == 1 or issue == "cursor" else None
                )
                if issue == "currency" and index == 2:
                    page["security"]["currency"] = "EUR"
                if issue == "venue" and index == 2:
                    page["security"]["exchange_mic"] = "XNAS"
                return httpx.Response(200, json=page)

            with self.subTest(issue=issue), self.provider(handler) as provider:
                with self.assertRaises(InvalidResponse):
                    provider.price_history(SECURITY_ID, START, END)
                self.assertEqual(len(requests), 2)

    def test_second_page_failure_does_not_return_a_successful_partial_chart(self):
        requests = []

        def handler(request):
            requests.append(request)
            if len(requests) == 1:
                return httpx.Response(200, json=payload([observation(START)], "token"))
            return httpx.Response(429, headers={"Retry-After": "120"}, text=TEST_KEY)

        with self.provider(handler) as provider, self.assertRaises(ProviderRateLimited) as error:
            provider.price_history(SECURITY_ID, START, END)
        self.assertEqual(error.exception.retry_after, 120)
        self.assertEqual(len(requests), 2)
        self.assertNotIn(TEST_KEY, str(error.exception))


class PriceChartTests(SimpleTestCase):
    def history(self, rows, start=START, end=END):
        return PriceHistory(
            Security(SECURITY_ID, "TSTF", "Fixture", "XNYS", None),
            tuple(rows),
            start,
            end,
            datetime.now(UTC),
            True,
        )

    def test_missing_adjusted_values_break_lines_without_raw_fallback(self):
        history = self.history(
            [
                DailyPrice(START, Decimal(10), Decimal(9), False),
                DailyPrice(START + timedelta(days=1), Decimal(11), None, False),
                DailyPrice(START + timedelta(days=2), Decimal(12), Decimal(11), False),
                DailyPrice(END, Decimal(20), Decimal(19), True),
            ]
        )
        chart = build_price_chart(history, "adjusted")
        self.assertEqual(len(chart.points), 2)
        self.assertEqual(len(chart.paths), 2)
        self.assertTrue(all(path.startswith("M") and "L" not in path for path in chart.paths))
        self.assertEqual(chart.latest.value, "11")
        self.assertEqual(chart.missing_count, 1)
        self.assertEqual(chart.unconfirmed_count, 1)
        self.assertEqual(chart.rows[0].period_status, "Incomplete period")
        self.assertEqual(chart.rows[2].adjusted_close, "Unavailable")
        self.assertEqual(len(build_price_chart(history, "raw").points), 3)

    def test_constant_zero_single_point_and_no_points_have_safe_coordinates(self):
        for values in [[Decimal(0)], [Decimal(10)] * 2, [None] * 2]:
            history = self.history(
                [
                    DailyPrice(START + timedelta(days=index), value, value, False)
                    for index, value in enumerate(values)
                ]
            )
            chart = build_price_chart(history, "raw")
            for point in chart.points:
                self.assertTrue(Decimal(point.x).is_finite())
                self.assertTrue(Decimal(point.y).is_finite())
                self.assertGreaterEqual(Decimal(point.y), 20)
                self.assertLessEqual(Decimal(point.y), 290)
            if values[0] is None:
                self.assertIsNone(chart.latest)
            else:
                self.assertEqual(chart.latest.value, str(values[-1]))

    def test_calendar_spacing_uses_dates_instead_of_trading_row_numbers(self):
        history = self.history(
            [
                DailyPrice(START, Decimal(10), Decimal(10), False),
                DailyPrice(START + timedelta(days=3), Decimal(12), Decimal(12), False),
                DailyPrice(START + timedelta(days=9), Decimal(11), Decimal(11), False),
            ],
            end=START + timedelta(days=9),
        )
        chart = build_price_chart(history, "raw")
        self.assertEqual([point.x for point in chart.points], ["95.000", "355.000", "875.000"])
        self.assertEqual(len(chart.paths), 1)
        with self.assertRaises(ValueError):
            build_price_chart(history, "unsupported")


@override_settings(INTRINIO_API_KEY=TEST_KEY)
class PriceViewTests(SimpleTestCase):
    def setUp(self):
        _request_budget.reset()
        self.addCleanup(_request_budget.reset)
        self.url = reverse("prices", args=[SECURITY_ID])
        self.query = {
            "start_date": START.isoformat(),
            "end_date": END.isoformat(),
            "basis": "adjusted",
        }

    def provider(self, handler):
        return patch(
            "research.services.IntrinioClient",
            side_effect=lambda key: IntrinioClient(key, transport=httpx.MockTransport(handler)),
        )

    def test_open_form_invalid_dates_basis_and_methods_make_no_provider_requests(self):
        with patch("research.services.IntrinioClient") as provider:
            response = self.client.get(self.url)
            self.assertContains(response, "No prices have been requested yet")
            for query in [
                {"basis": "raw"},
                {**self.query, "basis": "unknown"},
                {**self.query, "start_date": "bad"},
                {**self.query, "end_date": "2019-01-01"},
                {**self.query, "end_date": "2022-01-01"},
                {
                    **self.query,
                    "end_date": (datetime.now(UTC).date() + timedelta(days=1)).isoformat(),
                },
            ]:
                self.assertEqual(self.client.get(self.url, query).status_code, 400)
            self.assertEqual(self.client.head(self.url).status_code, 405)
            self.assertEqual(self.client.post(self.url, self.query).status_code, 405)
            self.assertEqual(
                self.client.get(reverse("prices", args=["invalid.id"])).status_code, 404
            )
        provider.assert_not_called()

    def test_adjusted_and_raw_chart_provenance_table_and_missing_states(self):
        with self.provider(lambda r: httpx.Response(200, json=fixture("daily_prices.json"))):
            adjusted = self.client.get(self.url, self.query)
            raw = self.client.get(self.url, {**self.query, "basis": "raw"})
        self.assertContains(adjusted, "Adjusted close · USD")
        self.assertContains(adjusted, "14.5 USD")
        self.assertContains(adjusted, "splits and dividends")
        self.assertContains(adjusted, "not a portfolio total-return calculation")
        self.assertContains(adjusted, "Period status unavailable")
        self.assertContains(adjusted, "2020-01-10")
        self.assertContains(adjusted, "1 returned observation lacks the selected close")
        self.assertContains(adjusted, "2 incomplete or unconfirmed periods excluded")
        self.assertEqual(len(adjusted.context["chart"].paths), 2)
        self.assertEqual(len(raw.context["chart"].paths), 1)
        self.assertContains(raw, "Raw close · USD")
        self.assertEqual(raw.headers["Cache-Control"], "no-store")
        self.assertNotContains(adjusted, TEST_KEY)

    def test_empty_missing_unknown_currency_and_zero_states_do_not_imply_prices(self):
        cases = [
            ([], "No completed closes available"),
            ([observation(START, adjusted=None)], "Latest plotted close"),
            ([observation(START, close=0, adjusted=0)], "0 on 2020-01-01"),
        ]
        for rows, _ in cases:
            data = payload(rows)
            data["security"]["currency"] = None
            with self.provider(lambda r, data=data: httpx.Response(200, json=data)):
                response = self.client.get(self.url, self.query)
            self.assertContains(response, "Unavailable — no currency assumed")
            self.assertNotContains(response, "USD")
            if not rows or rows[0]["adj_close"] is None:
                self.assertContains(response, "No completed closes available")
                self.assertNotContains(response, '<svg class="price-chart"')
            else:
                self.assertEqual(response.context["chart"].latest.value, "0")

    def test_partial_cap_is_explicit_and_missing_dates_do_not_claim_coverage(self):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(
                200,
                json=payload(
                    [observation(START + timedelta(days=len(requests)))], f"p-{len(requests)}"
                ),
            )

        with self.provider(handler):
            response = self.client.get(self.url, self.query)
        self.assertContains(response, "Partial history")
        self.assertContains(response, "No trading calendar is assumed")
        self.assertEqual(len(requests), MAX_PRICE_PAGES)

    def test_failure_states_keep_form_safe_and_have_no_chart(self):
        for status, expected in [(401, 503), (403, 503), (404, 404), (429, 429), (500, 503)]:
            _request_budget.reset()
            with self.subTest(status=status):
                with self.provider(
                    lambda r, status=status: httpx.Response(
                        status, text=TEST_KEY, headers={"Retry-After": "120"}
                    )
                ):
                    response = self.client.get(self.url, self.query)
                self.assertEqual(response.status_code, expected)
                self.assertContains(response, 'value="2020-01-01"', status_code=expected)
                self.assertNotContains(response, '<svg class="price-chart"', status_code=expected)
                self.assertNotContains(response, TEST_KEY, status_code=expected)
                if status == 429:
                    self.assertEqual(response.headers["Retry-After"], "120")

    @override_settings(INTRINIO_API_KEY="")
    def test_missing_credentials_never_contact_transport(self):
        with patch("research.services.IntrinioClient") as provider:
            response = self.client.get(self.url, self.query)
        self.assertContains(response, "Intrinio is not configured", status_code=503)
        provider.assert_not_called()

    def test_page_quota_is_shared_with_search_and_detail(self):
        requests = []
        for _ in range(9):
            _reserve_request("127.0.0.1")

        def handler(request):
            requests.append(request)
            return httpx.Response(200, json=payload([observation(START)], "next"))

        with self.provider(handler):
            response = self.client.get(self.url, self.query)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(len(requests), 1)
        self.assertNotContains(response, '<svg class="price-chart"', status_code=429)

    def test_credential_echo_and_wrong_data_cannot_render_a_chart(self):
        data = fixture("daily_prices.json")
        for case in [
            {**data, "security": {**data["security"], "name": TEST_KEY}},
            {**data, "stock_prices": [observation(date(2019, 1, 1))]},
        ]:
            with self.provider(lambda r, case=case: httpx.Response(200, json=case)):
                response = self.client.get(self.url, self.query)
            self.assertContains(response, 'data-error-code="invalid_response"', status_code=503)
            self.assertNotContains(response, TEST_KEY, status_code=503)

    def test_unexpected_failure_redacts_trace_and_provider_names_are_escaped(self):
        with patch("research.services.historical_prices", side_effect=RuntimeError(TEST_KEY)):
            with self.assertLogs("research", level="ERROR") as logs:
                response = self.client.get(self.url, self.query)
        self.assertNotContains(response, TEST_KEY, status_code=503)
        self.assertNotIn(TEST_KEY, "\n".join(logs.output))
        data = copy.deepcopy(fixture("daily_prices.json"))
        data["security"]["name"] = "<script>alert(1)</script>"
        with self.provider(lambda r: httpx.Response(200, json=data)):
            response = self.client.get(self.url, self.query)
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, "<script>alert(1)</script>")
