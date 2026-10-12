import copy
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

import httpx
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from market_data.errors import CompanyUnavailable, InvalidResponse, StatementUnavailable
from market_data.fundamentals import MAX_FINANCIAL_ROWS
from market_data.intrinio import IntrinioClient
from research.fundamentals import financial_text, metadata_time
from research.services import _request_budget, _reserve_request
from tests.test_intrinio import TEST_KEY, fixture

SECURITY = "sec_fixture_primary"
COMPANY = "com_fixture_company"
YEAR = 2019


def financial_fixture(statement_code="income_statement", period="FY", year=YEAR):
    fundamental = fixture("fundamental.json")
    fundamental.update(
        statement_code=statement_code,
        fiscal_period=period,
        fiscal_year=year,
        id=f"fun_fixture_{statement_code}_{year}_{period}",
    )
    dates = {
        "FY": (f"{year - 1}-10-01", f"{year}-09-30"),
        "Q1": (f"{year - 1}-10-01", f"{year - 1}-12-31"),
        "Q2": (f"{year}-01-01", f"{year}-03-31"),
        "Q3": (f"{year}-04-01", f"{year}-06-30"),
        "Q4": (f"{year}-07-01", f"{year}-09-30"),
    }
    fundamental["start_date"], fundamental["end_date"] = dates[period]
    if statement_code == "balance_sheet_statement":
        fundamental.update(type="restated", start_date=None)
    response = fixture("standardized_financials.json")
    response["fundamental"] = copy.deepcopy(fundamental)
    if statement_code != "income_statement":
        tags = (
            ["totalassets", "totalliabilities", "totalequity"]
            if statement_code == "balance_sheet_statement"
            else [
                "netcashfromoperatingactivities",
                "netcashfrominvestingactivities",
                "netcashfromfinancingactivities",
            ]
        )
        response["standardized_financials"] = [
            {
                "data_tag": {
                    "tag": tag,
                    "name": "Fixture " + tag,
                    "unit": "usd",
                    "sequence": index,
                },
                "value": (index + 1) * 1000,
            }
            for index, tag in enumerate(tags)
        ]
    return fundamental, response


def fixture_transport(request):
    if request.url.path == "/securities/search":
        return httpx.Response(200, json=fixture("security_search.json"))
    if request.url.path == "/securities/" + SECURITY:
        return httpx.Response(200, json=fixture("security_reference.json"))
    if "/fundamentals/lookup/" in request.url.path:
        statement, year, period = request.url.path.rsplit("/", 3)[-3:]
        fundamental, _ = financial_fixture(statement, period, int(year))
        return httpx.Response(200, json=fundamental)
    if request.url.path.endswith("/standardized_financials"):
        identifier = request.url.path.split("/")[-2]
        prefix, year, period = identifier.rsplit("_", 2)
        statement = prefix.removeprefix("fun_fixture_")
        _, financials = financial_fixture(statement, period, int(year))
        return httpx.Response(200, json=financials)
    return httpx.Response(404)


class FundamentalAdapterTests(SimpleTestCase):
    def provider(self, handler):
        return IntrinioClient(TEST_KEY, transport=httpx.MockTransport(handler))

    def statement(self, provider, **kwargs):
        return provider.financial_statement(SECURITY, "income_statement", YEAR, "FY", **kwargs)

    def test_explicit_company_period_and_three_bounded_requests_with_quota(self):
        requests, reservations = [], []

        def handler(request):
            requests.append(request)
            self.assertEqual(request.url.scheme, "https")
            self.assertEqual(request.url.host, "api-v2.intrinio.com")
            self.assertEqual(request.url.params["api_key"], TEST_KEY)
            return fixture_transport(request)

        with self.provider(handler) as provider:
            result = self.statement(provider, before_request=lambda: reservations.append(True))
        self.assertEqual(len(requests), 3)
        self.assertEqual(len(reservations), 3)
        self.assertIn(
            f"/companies/{COMPANY}/fundamentals/lookup/income_statement/2019/FY",
            [r.url.path for r in requests],
        )
        self.assertEqual(result.fundamental.fiscal_year, YEAR)
        self.assertEqual(result.fundamental.type, "reported")
        self.assertEqual(result.fundamental.start_date, date(2018, 10, 1))
        self.assertEqual(result.fundamental.end_date, date(2019, 9, 30))
        self.assertEqual(result.fundamental.company.id, COMPANY)
        self.assertEqual(result.fundamental.filing_date.tzinfo, UTC)
        self.assertEqual(result.retrieved_at.tzinfo, UTC)
        self.assertTrue(result.pagination_complete)
        self.assertEqual(result.values[0].tag, "totalrevenue")
        self.assertEqual(result.values[0].value, Decimal("1234567890.125"))

    def test_negative_zero_missing_values_and_tag_units_are_preserved(self):
        with self.provider(fixture_transport) as provider:
            result = self.statement(provider)
        values = {row.tag: row for row in result.values}
        self.assertEqual(values["netincome"].value, Decimal("-250000.5"))
        self.assertEqual(values["fixturezerometric"].value, 0)
        self.assertIsNone(values["dilutedeps"].value)
        self.assertIsNone(values["fixturezerometric"].unit)
        self.assertEqual(values["basiceps"].unit, "usdpershare")
        self.assertEqual(values["fixtureratio"].unit, "percentage")

    def test_restated_balance_sheet_is_preserved_as_point_in_time(self):
        with self.provider(fixture_transport) as provider:
            result = provider.financial_statement(SECURITY, "balance_sheet_statement", YEAR, "FY")
        self.assertEqual(result.fundamental.type, "restated")
        self.assertIsNone(result.fundamental.start_date)
        self.assertEqual(result.fundamental.end_date, date(2019, 9, 30))

    def test_all_three_statements_and_quarter_period_match_requested_metadata(self):
        with self.provider(fixture_transport) as provider:
            for code in ["income_statement", "balance_sheet_statement", "cash_flow_statement"]:
                for period in ["FY", "Q1", "Q2", "Q3", "Q4"]:
                    result = provider.financial_statement(SECURITY, code, YEAR, period)
                    self.assertEqual(result.fundamental.statement_code, code)
                    self.assertEqual(result.fundamental.fiscal_period, period)

    def test_invalid_requested_fields_do_not_reach_network(self):
        cases = [
            ("bad.id", "income_statement", YEAR, "FY"),
            (SECURITY, "other", YEAR, "FY"),
            (SECURITY, "balance_sheet", YEAR, "FY"),
            (SECURITY, "income_statement", YEAR, "TTM"),
            (SECURITY, "income_statement", 1899, "FY"),
            (SECURITY, "income_statement", datetime.now(UTC).year + 2, "FY"),
            (SECURITY, "income_statement", True, "FY"),
            (SECURITY, "income_statement", Decimal("2019"), "FY"),
        ]
        with self.provider(
            lambda r: self.fail("Invalid arguments must not spend quota")
        ) as provider:
            for args in cases:
                with self.subTest(args=args), self.assertRaises(ValueError):
                    provider.financial_statement(*args)

    def test_missing_company_stops_after_reference_without_ticker_fallback(self):
        requests = []

        def handler(request):
            requests.append(request)
            reference = fixture("security_reference.json")
            reference.pop("company_id")
            return httpx.Response(200, json=reference)

        with self.provider(handler) as provider, self.assertRaises(CompanyUnavailable):
            self.statement(provider)
        self.assertEqual(len(requests), 1)

    def test_wrong_security_or_unsafe_company_identifier_stops_before_lookup(self):
        for changes in [{"id": "sec_wrong"}, {"company_id": "../company"}, {"company_id": 1}]:
            reference = {**fixture("security_reference.json"), **changes}
            requests = []

            def handler(request, reference=reference, requests=requests):
                requests.append(request)
                return httpx.Response(200, json=reference)

            with self.provider(handler) as provider, self.assertRaises(InvalidResponse):
                self.statement(provider)
            self.assertEqual(len(requests), 1)

    def test_lookup_and_values_metadata_must_match_company_statement_year_period(self):
        cases = [
            {"company": {"id": "com_other"}},
            {"statement_code": "balance_sheet_statement"},
            {"fiscal_year": YEAR - 1},
            {"fiscal_year": str(YEAR)},
            {"fiscal_year": True},
            {"fiscal_period": "Q1"},
            {"id": "bad.identifier"},
            {"type": "forecast"},
            {"start_date": "2020-01-01"},
            {"end_date": "2019-99-31"},
            {"end_date": "9999-01-01"},
            {"filing_date": "not-a-date"},
            {"start_date": "20181001"},
        ]
        for stage in ["lookup", "values"]:
            for change in cases:

                def handler(request, stage=stage, change=change):
                    result = fixture_transport(request)
                    if stage == "lookup" and "/lookup/" in request.url.path:
                        return httpx.Response(200, json={**result.json(), **change})
                    if stage == "values" and request.url.path.endswith("standardized_financials"):
                        data = result.json()
                        data["fundamental"].update(change)
                        return httpx.Response(200, json=data)
                    return result

                with self.subTest(stage=stage, change=change), self.provider(handler) as provider:
                    with self.assertRaises(InvalidResponse):
                        self.statement(provider)

    def test_changed_fundamental_identity_type_or_dates_between_calls_fail(self):
        for change in [{"id": "fun_other"}, {"type": "calculated"}, {"start_date": "2018-10-02"}]:

            def handler(request, change=change):
                response = fixture_transport(request)
                if request.url.path.endswith("standardized_financials"):
                    data = response.json()
                    data["fundamental"].update(change)
                    return httpx.Response(200, json=data)
                return response

            with self.provider(handler) as provider, self.assertRaises(InvalidResponse):
                self.statement(provider)

    def test_missing_optional_dates_types_names_units_remain_unavailable(self):
        def handler(request):
            response = fixture_transport(request)
            data = response.json()
            if "/lookup/" in request.url.path or request.url.path.endswith(
                "standardized_financials"
            ):
                fundamental = data["fundamental"] if "fundamental" in data else data
                for key in [
                    "start_date",
                    "end_date",
                    "filing_date",
                    "updated_date",
                    "first_calculable",
                    "type",
                ]:
                    fundamental.pop(key, None)
                fundamental["company"] = {"id": COMPANY}
            return httpx.Response(200, json=data)

        with self.provider(handler) as provider:
            result = self.statement(provider)
        self.assertIsNone(result.fundamental.company.name)
        self.assertIsNone(result.fundamental.start_date)
        self.assertIsNone(result.fundamental.filing_date)
        self.assertIsNone(result.fundamental.type)

    def test_unknown_timezones_and_date_only_filings_are_preserved(self):
        def handler(request):
            response = fixture_transport(request)
            data = response.json()
            if "/lookup/" in request.url.path or "fundamental" in data:
                f = data.get("fundamental", data)
                f.update(filing_date="2019-10-31", updated_date="2020-01-15T12:00:00")
            return httpx.Response(200, json=data)

        with self.provider(handler) as provider:
            result = self.statement(provider)
        self.assertEqual(result.fundamental.filing_date, date(2019, 10, 31))
        self.assertIsNone(result.fundamental.updated_date.tzinfo)
        self.assertEqual(metadata_time(result.fundamental.filing_date), "2019-10-31 (date only)")
        self.assertIn("timezone unavailable", metadata_time(result.fundamental.updated_date))

    def test_numeric_json_precision_retains_financial_decimals_without_rounding(self):
        def handler(request):
            response = fixture_transport(request)
            if request.url.path.endswith("standardized_financials"):
                text = json.dumps(response.json()).replace(
                    '"value": -0.25', '"value": -0.123456789012345678'
                )
                return httpx.Response(200, content=text)
            return response

        with self.provider(handler) as provider:
            result = self.statement(provider)
        value = next(row.value for row in result.values if row.tag == "basiceps")
        self.assertEqual(value, Decimal("-0.123456789012345678"))

    def test_invalid_numbers_tag_units_duplicate_tags_and_size_are_rejected(self):
        base = fixture("standardized_financials.json")["standardized_financials"]
        cases = [None, [None], [{}], base * 2, base * (MAX_FINANCIAL_ROWS // len(base) + 1)]
        for value in [True, "10", [], 1e25, 1e-19]:
            rows = copy.deepcopy(base)
            rows[0]["value"] = value
            cases.append(rows)
        for changes in [
            {"tag": "bad/tag"},
            {"tag": ""},
            {"unit": 1},
            {"unit": "bad\nunit"},
            {"sequence": "1"},
            {"sequence": 1000001},
            {"name": "x" * 513},
        ]:
            rows = copy.deepcopy(base)
            rows[0]["data_tag"].update(changes)
            cases.append(rows)
        for rows in cases:

            def handler(request, rows=rows):
                response = fixture_transport(request)
                if request.url.path.endswith("standardized_financials"):
                    data = response.json()
                    data["standardized_financials"] = rows
                    return httpx.Response(200, json=data)
                return response

            with self.provider(handler) as provider, self.assertRaises(InvalidResponse):
                self.statement(provider)

    def test_nonfinite_and_extreme_zero_exponent_do_not_expand_html(self):
        for number in ["NaN", "Infinity", "0e999999", "-1e999999", "1e-999999"]:

            def handler(request, number=number):
                response = fixture_transport(request)
                if request.url.path.endswith("standardized_financials"):
                    text = json.dumps(response.json()).replace(
                        '"value": -0.25', '"value": ' + number
                    )
                    return httpx.Response(200, content=text)
                return response

            with self.provider(handler) as provider, self.assertRaises(InvalidResponse):
                self.statement(provider)

    def test_pagination_cursor_marks_partial_without_unsupported_follow_up(self):
        requests = []

        def handler(request):
            requests.append(request)
            response = fixture_transport(request)
            if request.url.path.endswith("standardized_financials"):
                data = response.json()
                data["next_page"] = "opaque+/= token"
                return httpx.Response(200, json=data)
            return response

        with self.provider(handler) as provider:
            result = self.statement(provider)
        self.assertFalse(result.pagination_complete)
        self.assertEqual(len(requests), 3)

    def test_missing_and_null_cursor_mean_no_indicated_continuation(self):
        for explicit_null in [False, True]:

            def handler(request, explicit_null=explicit_null):
                response = fixture_transport(request)
                if request.url.path.endswith("standardized_financials"):
                    data = response.json()
                    if explicit_null:
                        data["next_page"] = None
                    return httpx.Response(200, json=data)
                return response

            with self.provider(handler) as provider:
                result = self.statement(provider)
            self.assertTrue(result.pagination_complete)
            self.assertEqual(len(result.values), 7)

    def test_invalid_cursor_does_not_claim_complete_statement(self):
        for cursor in ["", 123, "x" * 1025, "bad\n"]:

            def handler(request, cursor=cursor):
                response = fixture_transport(request)
                if request.url.path.endswith("standardized_financials"):
                    data = response.json()
                    data["next_page"] = cursor
                    return httpx.Response(200, json=data)
                return response

            with self.provider(handler) as provider, self.assertRaises(InvalidResponse):
                self.statement(provider)

    def test_lookup_or_values_404_is_a_missing_statement_not_missing_security(self):
        for stage in ["lookup", "values"]:

            def handler(request, stage=stage):
                if (stage == "lookup" and "/lookup/" in request.url.path) or (
                    stage == "values" and request.url.path.endswith("standardized_financials")
                ):
                    return httpx.Response(404)
                return fixture_transport(request)

            with self.provider(handler) as provider, self.assertRaises(StatementUnavailable):
                self.statement(provider)


@override_settings(INTRINIO_API_KEY=TEST_KEY)
class StatementViewTests(SimpleTestCase):
    def setUp(self):
        _request_budget.reset()
        self.addCleanup(_request_budget.reset)
        self.url = reverse("financials", args=[SECURITY])
        self.query = {
            "statement_code": "income_statement",
            "fiscal_year": YEAR,
            "fiscal_period": "FY",
        }

    def provider(self, handler=fixture_transport):
        return patch(
            "research.services.IntrinioClient",
            side_effect=lambda key: IntrinioClient(key, transport=httpx.MockTransport(handler)),
        )

    def test_form_invalid_requests_and_unsafe_methods_do_not_request_data(self):
        with patch("research.services.IntrinioClient") as provider:
            self.assertContains(
                self.client.get(self.url), "No financial data has been requested yet"
            )
            for query in [
                {"statement_code": "income_statement"},
                {**self.query, "statement_code": "other"},
                {**self.query, "fiscal_year": 1899},
                {**self.query, "fiscal_year": "2020.5"},
                {**self.query, "fiscal_year": datetime.now(UTC).year + 2},
                {**self.query, "fiscal_period": "TTM"},
            ]:
                self.assertEqual(self.client.get(self.url, query).status_code, 400)
            self.assertEqual(self.client.post(self.url, self.query).status_code, 405)
            self.assertEqual(self.client.head(self.url).status_code, 405)
            self.assertEqual(
                self.client.get(reverse("financials", args=["bad.id"])).status_code, 404
            )
        provider.assert_not_called()

    def test_statement_metrics_units_zero_negative_missing_and_provenance_render(self):
        with self.provider():
            response = self.client.get(self.url, self.query)
        self.assertContains(response, "Income statement · 2019 FY")
        self.assertContains(response, "1,234,567,890.125")
        self.assertContains(response, "-250,000.5")
        self.assertContains(response, "USD per share")
        self.assertContains(response, "Shares")
        self.assertContains(response, "percentage (provider unit; no conversion)")
        self.assertContains(response, "Unavailable — no unit inferred")
        self.assertContains(response, "Value not supplied")
        self.assertContains(response, "Provider-reported period")
        self.assertContains(response, "2018-10-01")
        self.assertContains(response, "2019-09-30")
        self.assertContains(response, "SEC filing date/time")
        self.assertContains(response, "may include restatements")
        self.assertContains(response, "not a point-in-time backtest dataset")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertNotContains(response, TEST_KEY)
        metrics = {metric.tag: metric for metric in response.context["metrics"]}
        self.assertEqual(metrics["basiceps"].value, "-0.25")
        self.assertEqual(financial_text(Decimal(0)), "0")

    def test_balance_sheet_is_point_in_time_and_cash_flow_has_period_definitions(self):
        for code, expected in [
            ("balance_sheet_statement", "point in time"),
            ("cash_flow_statement", "Operating cash flow"),
        ]:
            _request_budget.reset()
            with self.provider():
                response = self.client.get(self.url, {**self.query, "statement_code": code})
            self.assertContains(response, expected)

    def test_calculated_quarter_is_labeled_without_invented_annual_or_ttm_metrics(self):
        def handler(request):
            response = fixture_transport(request)
            data = response.json()
            if "/lookup/" in request.url.path or "fundamental" in data:
                data.get("fundamental", data)["type"] = "calculated"
            return httpx.Response(200, json=data)

        with self.provider(handler):
            response = self.client.get(self.url, {**self.query, "fiscal_period": "Q4"})
        self.assertContains(response, "2019 Q4")
        self.assertContains(response, "Provider-calculated period")
        self.assertContains(response, "Trailing metrics")

    def test_empty_values_and_absent_key_tags_are_unavailable(self):
        for empty in [True, False]:

            def handler(request, empty=empty):
                response = fixture_transport(request)
                data = response.json()
                if request.url.path.endswith("standardized_financials"):
                    data["standardized_financials"] = (
                        [] if empty else [data["standardized_financials"][-1]]
                    )
                return httpx.Response(200, json=data)

            _request_budget.reset()
            with self.provider(handler):
                response = self.client.get(self.url, self.query)
            self.assertContains(
                response,
                "No financial values supplied" if empty else "Tag not supplied in this response",
            )

    def test_partial_response_is_labeled_not_silently_completed(self):
        def handler(request):
            response = fixture_transport(request)
            data = response.json()
            if request.url.path.endswith("standardized_financials"):
                data["next_page"] = "more"
            return httpx.Response(200, json=data)

        with self.provider(handler):
            response = self.client.get(self.url, self.query)
        self.assertContains(response, "Partial statement")
        self.assertContains(response, "Missing tags here do not establish")

    def test_each_stage_failure_is_safe_and_does_not_show_financial_values(self):
        for stage in ["reference", "lookup", "values"]:
            for status, public_status in [
                (401, 503),
                (403, 503),
                (404, 404),
                (429, 429),
                (500, 503),
            ]:
                requests = []

                def handler(request, stage=stage, status=status, requests=requests):
                    requests.append(request)
                    current = (
                        "reference"
                        if request.url.path.startswith("/securities/")
                        else "lookup"
                        if "/lookup/" in request.url.path
                        else "values"
                    )
                    if current == stage:
                        return httpx.Response(status, text=TEST_KEY, headers={"Retry-After": "120"})
                    return fixture_transport(request)

                _request_budget.reset()
                with self.subTest(stage=stage, status=status), self.provider(handler):
                    response = self.client.get(self.url, self.query)
                self.assertEqual(response.status_code, public_status)
                self.assertContains(response, 'value="2019"', status_code=public_status)
                self.assertNotContains(response, "financial-table", status_code=public_status)
                self.assertNotContains(response, "1,234,567,890.125", status_code=public_status)
                self.assertNotContains(response, TEST_KEY, status_code=public_status)
                self.assertEqual(len(requests), {"reference": 1, "lookup": 2, "values": 3}[stage])
                if status == 429:
                    self.assertEqual(response.headers["Retry-After"], "120")

    @override_settings(INTRINIO_API_KEY="")
    def test_missing_credentials_do_not_construct_transport(self):
        with patch("research.services.IntrinioClient") as provider:
            response = self.client.get(self.url, self.query)
        self.assertContains(response, "not configured", status_code=503)
        provider.assert_not_called()

    def test_quota_is_reserved_at_each_stage_and_failure_discards_partial_values(self):
        requests = []
        for _ in range(8):
            _reserve_request("127.0.0.1")

        def handler(request):
            requests.append(request)
            return fixture_transport(request)

        with self.provider(handler):
            response = self.client.get(self.url, self.query)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(len(requests), 2)
        self.assertNotContains(response, "1,234,567,890.125", status_code=429)

    def test_listing_currency_is_not_used_as_the_statement_currency(self):
        def handler(request):
            response = fixture_transport(request)
            data = response.json()
            if request.url.path.startswith("/securities/"):
                data["currency"] = "CAD"
            return httpx.Response(200, json=data)

        with self.provider(handler):
            response = self.client.get(self.url, self.query)
        self.assertContains(response, "CAD")
        self.assertContains(response, "USD per share")
        self.assertContains(response, "Listing currency is not used to infer")

    def test_xss_and_credential_echo_in_statement_fields_are_handled_safely(self):
        for text, expected_status in [("<script>alert(1)</script>", 200), (TEST_KEY, 503)]:

            def handler(request, text=text):
                response = fixture_transport(request)
                data = response.json()
                if request.url.path.endswith("standardized_financials"):
                    data["standardized_financials"][0]["data_tag"]["name"] = text
                return httpx.Response(200, json=data)

            _request_budget.reset()
            with self.provider(handler):
                response = self.client.get(self.url, self.query)
            self.assertEqual(response.status_code, expected_status)
            self.assertNotContains(
                response, "<script>alert(1)</script>", status_code=expected_status
            )
            self.assertNotContains(response, TEST_KEY, status_code=expected_status)
            if expected_status == 200:
                self.assertContains(response, "&lt;script&gt;")

    def test_unexpected_failure_uses_safe_page_and_redacted_trace(self):
        with patch("research.services.company_statement", side_effect=RuntimeError(TEST_KEY)):
            with self.assertLogs("research", level="ERROR") as logs:
                response = self.client.get(self.url, self.query)
        self.assertNotContains(response, TEST_KEY, status_code=503)
        self.assertNotIn(TEST_KEY, "\n".join(logs.output))


@override_settings(INTRINIO_API_KEY=TEST_KEY)
class FundamentalCommandTests(SimpleTestCase):
    def setUp(self):
        _request_budget.reset()
        self.addCleanup(_request_budget.reset)

    def provider(self, handler):
        return patch(
            "research.services.IntrinioClient",
            side_effect=lambda key: IntrinioClient(key, transport=httpx.MockTransport(handler)),
        )

    def test_mock_success_makes_four_requests_without_claiming_forecasts_or_asof_history(self):
        requests = []

        def handler(request):
            requests.append(request)
            return fixture_transport(request)

        output = StringIO()
        with self.provider(handler):
            call_command("verify_fundamentals", fiscal_year=YEAR, stdout=output)
        self.assertEqual(len(requests), 4)
        self.assertIn("6 supplied numeric observations", output.getvalue())
        self.assertIn("point-in-time history", output.getvalue())
        self.assertNotIn(TEST_KEY, output.getvalue())

    @override_settings(INTRINIO_API_KEY="")
    def test_missing_credentials_fail_acceptance(self):
        with patch("research.services.IntrinioClient") as provider:
            with self.assertRaises(CommandError):
                call_command("verify_fundamentals", fiscal_year=YEAR, stdout=StringIO())
        provider.assert_not_called()

    def test_invalid_parameters_make_no_requests(self):
        with patch("research.services.IntrinioClient") as provider:
            for options in [
                {"query": ""},
                {"fiscal_year": 1899},
                {"statement_code": "other"},
                {"fiscal_period": "TTM"},
            ]:
                with self.assertRaises(CommandError):
                    call_command("verify_fundamentals", stdout=StringIO(), **options)
        provider.assert_not_called()

    def test_empty_search_no_values_all_missing_denial_and_partial_fail_acceptance(self):
        for case in ["search", "empty", "missing", "denied", "partial"]:

            def handler(request, case=case):
                response = fixture_transport(request)
                data = response.json()
                if request.url.path.endswith("search") and case == "search":
                    data["securities"] = []
                if request.url.path.endswith("standardized_financials"):
                    if case == "denied":
                        return httpx.Response(403, text=TEST_KEY)
                    if case == "empty":
                        data["standardized_financials"] = []
                    if case == "missing":
                        for row in data["standardized_financials"]:
                            row["value"] = None
                    if case == "partial":
                        data["next_page"] = "more"
                return httpx.Response(200, json=data)

            _request_budget.reset()
            with self.subTest(case=case), self.provider(handler), self.assertRaises(CommandError):
                call_command("verify_fundamentals", fiscal_year=YEAR, stdout=StringIO())
