"""Independent average-balance examples, seven-request bounds and page failures."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal, localcontext
from unittest.mock import patch

import httpx
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from market_data.contracts import (
    AnnualProfitabilityStatements,
    Company,
    FinancialValue,
)
from market_data.errors import InvalidResponse, ProviderError, ProviderRateLimited
from market_data.intrinio import IntrinioClient
from research.capital_return_forms import CapitalReturnForm
from research.capital_returns import calculate_capital_returns
from research.financial_math import average_balance
from research.services import _request_budget, annual_profitability
from tests.test_fundamentals import SECURITY, YEAR, financial_fixture, fixture_transport
from tests.test_intrinio import TEST_KEY
from tests.test_profitability import statement


def capital_bundle(net="120", assets=("1000", "1200"), equity=("500", "700")):
    income = statement(net=net)
    security = replace(income.security, company_id="com_fixture")
    income = replace(income, security=security)
    balances = []
    for index, end in enumerate((date(2018, 9, 30), date(2019, 9, 30))):
        balances.append(
            replace(
                income,
                fundamental=replace(
                    income.fundamental,
                    id=f"fun_balance_{index}",
                    statement_code="balance_sheet_statement",
                    fiscal_year=2018 + index,
                    start_date=None,
                    end_date=end,
                ),
                values=(
                    FinancialValue("totalassets", None, "usd", Decimal(assets[index]), None),
                    FinancialValue("totalequity", None, "usd", Decimal(equity[index]), None),
                ),
            )
        )
    return AnnualProfitabilityStatements(income, *balances)


def change_source(bundle, scope, *, tag=None, **changes):
    source = getattr(bundle, scope)
    if tag is None:
        source = replace(source, **changes)
    else:
        source = replace(
            source,
            values=tuple(
                replace(row, **changes) if row.tag == tag else row for row in source.values
            ),
        )
    return replace(bundle, **{scope: source})


def capital_fixture_transport(request):
    """Invented values used only by tests and the optional loopback server."""
    path = request.url.path
    if "/fundamentals/lookup/" in path:
        code, year, period = path.rsplit("/", 3)[-3:]
        year = int(year)
        if code == "income_statement" and year in (2015, 2016, 2017):
            return httpx.Response(
                {2015: 429, 2016: 403, 2017: 404}[year],
                headers={"Retry-After": "60"},
                text=TEST_KEY,
            )
        fundamental, _ = financial_fixture(code, period, year)
        return httpx.Response(200, json=fundamental)
    if path.endswith("/standardized_financials"):
        prefix, year, period = path.split("/")[-2].rsplit("_", 2)
        code, year = prefix.removeprefix("fun_fixture_"), int(year)
        _, payload = financial_fixture(code, period, year)
        observations = (
            (
                ("totalrevenue", 1000),
                ("grossprofit", 400),
                ("operatingincome", 200),
                ("netincome", 120),
            )
            if code == "income_statement"
            else (
                ("totalassets", 1000 if year == 2018 else 1200),
                ("totalequity", 500 if year == 2018 else 700),
            )
        )
        payload["standardized_financials"] = [
            {
                "data_tag": {"tag": tag, "name": "Fixture " + tag, "unit": "usd", "sequence": i},
                "value": value,
            }
            for i, (tag, value) in enumerate(observations)
        ]
        return httpx.Response(200, json=payload)
    return fixture_transport(request)


class CapitalReturnCalculationTests(SimpleTestCase):
    def result(self, bundle=None):
        return calculate_capital_returns(bundle or capital_bundle())

    def unavailable(self, bundle, text):
        result = self.result(bundle)
        for metric in result.metrics:
            self.assertIsNone(metric.percent)
            self.assertIn(text, metric.issue)

    def test_hand_calculated_average_balances_and_returns(self):
        result = self.result()
        self.assertEqual(result.net_income, Decimal("120"))
        self.assertEqual(
            tuple(row.average for row in result.metrics), (Decimal("1100"), Decimal("600"))
        )
        self.assertEqual(
            tuple(row.percent for row in result.metrics), (Decimal("10.91"), Decimal("20.00"))
        )
        self.assertIsNone(result.alignment_issue)

    def test_net_loss_and_zero_remain_valid_observations(self):
        for net, expected in (("-120", ("-10.91", "-20.00")), ("0", ("0.00", "0.00"))):
            self.assertEqual(
                tuple(str(row.percent) for row in self.result(capital_bundle(net=net)).metrics),
                expected,
            )

    def test_half_up_percentages_use_unrounded_average(self):
        result = self.result(
            capital_bundle(net="1.005", assets=("100", "100"), equity=("100", "100"))
        )
        self.assertEqual(result.metrics[0].percent, Decimal("1.01"))
        result = self.result(
            capital_bundle(net="-1.005", assets=("100", "100"), equity=("100", "100"))
        )
        self.assertEqual(result.metrics[1].percent, Decimal("-1.01"))
        result = self.result(capital_bundle(net="1", assets=("1.01", "1.02")))
        self.assertEqual(result.metrics[0].average, Decimal("1.015"))
        self.assertEqual(result.metrics[0].percent, Decimal("98.52"))

    def test_tiny_negative_zero_and_values_above_one_hundred(self):
        self.assertEqual(
            str(self.result(capital_bundle(net="-0.00001")).metrics[0].percent), "0.00"
        )
        self.assertEqual(
            self.result(capital_bundle(net="2400")).metrics[1].percent, Decimal("400.00")
        )

    def test_nonpositive_equity_does_not_disable_valid_assets(self):
        for equity in (
            ("0", "700"),
            ("500", "0"),
            ("-100", "700"),
            ("500", "-700"),
            ("-500", "-700"),
        ):
            result = self.result(capital_bundle(equity=equity))
            self.assertEqual(result.metrics[0].percent, Decimal("10.91"))
            self.assertIsNone(result.metrics[1].percent)
            self.assertIn("Both endpoint balances must be positive", result.metrics[1].issue)

    def test_nonpositive_assets_leave_equity_independent(self):
        result = self.result(capital_bundle(assets=("0", "1200")))
        self.assertIsNone(result.metrics[0].percent)
        self.assertEqual(result.metrics[1].percent, Decimal("20.00"))

    def test_missing_or_null_net_income_withholds_both_returns(self):
        source = capital_bundle()
        self.unavailable(
            change_source(source, "income", tag="netincome", value=None), "source value netincome"
        )
        income = replace(
            source.income,
            values=tuple(row for row in source.income.values if row.tag != "netincome"),
        )
        self.unavailable(replace(source, income=income), "source tag netincome")

    def test_missing_null_or_bad_endpoint_value_is_per_metric(self):
        source = capital_bundle()
        for scope in ("opening_balance", "closing_balance"):
            for value in (
                None,
                Decimal("NaN"),
                Decimal("sNaN"),
                Decimal("Infinity"),
                Decimal("1e25"),
                Decimal("1e-19"),
                True,
                1,
                1.0,
            ):
                result = self.result(change_source(source, scope, tag="totalassets", value=value))
                self.assertIsNone(result.metrics[0].percent)
                self.assertEqual(result.metrics[1].percent, Decimal("20.00"))
            current = getattr(source, scope)
            result = self.result(
                change_source(
                    source,
                    scope,
                    values=tuple(row for row in current.values if row.tag != "totalassets"),
                )
            )
            self.assertIn("source tag totalassets", result.metrics[0].issue)

    def test_net_income_requires_finite_bounded_decimal(self):
        for value in (
            Decimal("NaN"),
            Decimal("sNaN"),
            Decimal("Infinity"),
            Decimal("1e25"),
            Decimal("1e-19"),
            True,
            1,
            "120",
        ):
            self.unavailable(
                change_source(capital_bundle(), "income", tag="netincome", value=value),
                "finite financial number",
            )

    def test_net_and_endpoint_units_are_explicit_not_listing_currency(self):
        source = capital_bundle()
        for unit in (None, "USD", "eur", "usdpershare", "usd_millions", "shares", "percentage"):
            self.unavailable(
                change_source(source, "income", tag="netincome", unit=unit),
                "explicit provider unit of usd",
            )
            result = self.result(
                change_source(source, "closing_balance", tag="totalequity", unit=unit)
            )
            self.assertIsNone(result.metrics[1].percent)
            self.assertEqual(result.metrics[0].percent, Decimal("10.91"))
        for scope in ("income", "opening_balance", "closing_balance"):
            current = getattr(source, scope)
            source = change_source(
                source, scope, security=replace(current.security, currency="EUR")
            )
        self.assertEqual(self.result(source).metrics[0].percent, Decimal("10.91"))

    def test_company_and_instrument_identities_must_match(self):
        for scope in ("income", "opening_balance", "closing_balance"):
            source = capital_bundle()
            current = getattr(source, scope)
            self.unavailable(
                change_source(
                    source,
                    scope,
                    fundamental=replace(
                        current.fundamental, company=Company("com_other", None, None)
                    ),
                ),
                "same verified",
            )
            self.unavailable(
                change_source(source, scope, security=replace(current.security, company_id=None)),
                "same verified",
            )
        self.unavailable(
            change_source(
                capital_bundle(),
                "opening_balance",
                security=replace(capital_bundle().opening_balance.security, id="sec_other"),
            ),
            "same verified",
        )

    def test_expected_statement_types_fiscal_years_and_annual_periods(self):
        source = capital_bundle()
        for scope, changes in (
            ("income", {"statement_code": "cash_flow_statement"}),
            ("closing_balance", {"statement_code": "income_statement"}),
            ("income", {"fiscal_period": "Q4"}),
            ("opening_balance", {"fiscal_period": "Q4"}),
            ("closing_balance", {"fiscal_period": "Q4"}),
            ("opening_balance", {"fiscal_year": 2017}),
            ("closing_balance", {"fiscal_year": 2020}),
            ("income", {"fiscal_year": True}),
        ):
            current = getattr(source, scope)
            self.unavailable(
                change_source(source, scope, fundamental=replace(current.fundamental, **changes)),
                "annual income statement",
            )

    def test_income_dates_cannot_be_missing_reversed_same_day_or_timestamps(self):
        source = capital_bundle()
        for start, end in (
            (None, date(2019, 9, 30)),
            (date(2018, 10, 1), None),
            (date(2019, 9, 30), date(2019, 9, 30)),
            (date(2020, 1, 1), date(2019, 9, 30)),
            (datetime(2018, 10, 1), date(2019, 9, 30)),
        ):
            self.unavailable(
                change_source(
                    source,
                    "income",
                    fundamental=replace(source.income.fundamental, start_date=start, end_date=end),
                ),
                "valid supplied start and end dates",
            )

    def test_balance_dates_must_match_exact_boundaries(self):
        source = capital_bundle()
        for scope in ("opening_balance", "closing_balance"):
            for end in (None, date(2019, 1, 1), datetime(2018, 9, 30)):
                current = getattr(source, scope)
                self.unavailable(
                    change_source(
                        source, scope, fundamental=replace(current.fundamental, end_date=end)
                    ),
                    "day before income starts",
                )

    def test_shifted_fiscal_year_and_leap_day_need_no_calendar_inference(self):
        source = capital_bundle()
        source = change_source(
            source,
            "income",
            fundamental=replace(
                source.income.fundamental,
                fiscal_year=2020,
                start_date=date(2019, 3, 1),
                end_date=date(2020, 2, 29),
            ),
        )
        source = change_source(
            source,
            "opening_balance",
            fundamental=replace(
                source.opening_balance.fundamental, fiscal_year=2019, end_date=date(2019, 2, 28)
            ),
        )
        source = change_source(
            source,
            "closing_balance",
            fundamental=replace(
                source.closing_balance.fundamental, fiscal_year=2020, end_date=date(2020, 2, 29)
            ),
        )
        self.assertEqual(self.result(source).metrics[0].percent, Decimal("10.91"))

    def test_partial_or_duplicate_response_in_any_input_withholds_all(self):
        for scope in ("income", "opening_balance", "closing_balance"):
            source = capital_bundle()
            self.unavailable(
                change_source(source, scope, pagination_complete=False), "must be complete"
            )
            current = getattr(source, scope)
            self.unavailable(
                change_source(source, scope, values=(*current.values, current.values[0])),
                "Duplicate source tags",
            )

    def test_classifications_do_not_claim_one_historical_version(self):
        source = capital_bundle()
        for scope, kind in (
            ("income", "reported"),
            ("opening_balance", "restated"),
            ("closing_balance", "calculated"),
        ):
            current = getattr(source, scope)
            source = change_source(
                source, scope, fundamental=replace(current.fundamental, type=kind)
            )
        self.assertEqual(self.result(source).metrics[1].percent, Decimal("20.00"))

    def test_exact_average_and_ratios_ignore_decimal_context_and_traps(self):
        source = capital_bundle(net="1", assets=("1.01", "1.02"))
        with localcontext() as context:
            context.prec, context.Emax, context.Emin = 2, 1, -1
            for signal in context.traps:
                context.traps[signal] = True
            result = self.result(source)
        self.assertEqual(result.metrics[0].average, Decimal("1.015"))
        self.assertEqual(result.metrics[0].percent, Decimal("98.52"))

    def test_extreme_valid_values_do_not_round_endpoint_average(self):
        source = capital_bundle(net="1e24", assets=("1e-18", "2e-18"))
        result = self.result(source).metrics[0]
        self.assertEqual(result.average, Decimal("1.5e-18"))
        self.assertEqual(result.percent, Decimal("66666666666666666666666666666666666666666666.67"))

    def test_average_balance_exact_examples_with_different_exponents(self):
        self.assertEqual(average_balance(Decimal("1e3"), Decimal("1200.001")), Decimal("1100.0005"))
        self.assertEqual(average_balance(Decimal("1e-18"), Decimal("2e-18")), Decimal("1.5e-18"))


class AnnualProfitabilityAdapterTests(SimpleTestCase):
    def test_one_security_three_lookup_value_pairs_and_seven_quota_reservations(self):
        requests, reservations = [], []

        def handler(request):
            requests.append(request)
            return capital_fixture_transport(request)

        with IntrinioClient(TEST_KEY, transport=httpx.MockTransport(handler)) as provider:
            result = provider.annual_profitability(
                SECURITY, YEAR, before_request=lambda: reservations.append(True)
            )
        self.assertEqual(len(requests), 7)
        self.assertEqual(len(reservations), 7)
        self.assertEqual(
            sum(request.url.path.startswith("/securities/") for request in requests), 1
        )
        self.assertEqual(
            [
                source.fundamental.fiscal_year
                for source in (result.income, result.opening_balance, result.closing_balance)
            ],
            [2019, 2018, 2019],
        )
        self.assertEqual(calculate_capital_returns(result).metrics[0].percent, Decimal("10.91"))

    def test_invalid_year_or_identifier_spends_no_request(self):
        requests = []
        with IntrinioClient(
            TEST_KEY, transport=httpx.MockTransport(lambda request: requests.append(request))
        ) as provider:
            for security, year in (
                ("bad.id", YEAR),
                (SECURITY, 1900),
                (SECURITY, True),
                (SECURITY, 1.5),
                (SECURITY, datetime.now(UTC).year + 2),
            ):
                with self.assertRaises(ValueError):
                    provider.annual_profitability(security, year)
        self.assertEqual(requests, [])

    def test_failure_at_any_stage_stops_without_fallback_or_retry(self):
        for stage in range(1, 8):
            for status in (403, 429, 404):
                requests = []

                def handler(request, stage=stage, status=status, requests=requests):
                    requests.append(request)
                    return (
                        httpx.Response(status, headers={"Retry-After": "60"}, text=TEST_KEY)
                        if len(requests) == stage
                        else capital_fixture_transport(request)
                    )

                with IntrinioClient(TEST_KEY, transport=httpx.MockTransport(handler)) as provider:
                    with self.assertRaises(ProviderError):
                        provider.annual_profitability(SECURITY, YEAR)
                self.assertEqual(len(requests), stage)

    def test_quota_denial_before_each_request_stops_transport(self):
        for stage in range(1, 8):
            requests, reservations = [], []

            def reserve(stage=stage, reservations=reservations):
                reservations.append(True)
                if len(reservations) == stage:
                    raise ProviderRateLimited(17)

            def handler(request, requests=requests):
                requests.append(request)
                return capital_fixture_transport(request)

            with IntrinioClient(TEST_KEY, transport=httpx.MockTransport(handler)) as provider:
                with self.assertRaises(ProviderRateLimited):
                    provider.annual_profitability(SECURITY, YEAR, before_request=reserve)
            self.assertEqual(len(requests), stage - 1)

    def test_changed_company_period_and_lookup_value_dates_are_rejected(self):
        for field, value in (
            ("end_date", "2019-09-29"),
            ("fiscal_year", 2020),
            ("fiscal_period", "Q4"),
        ):

            def handler(request, field=field, value=value):
                response = capital_fixture_transport(request)
                if request.url.path.endswith("/standardized_financials"):
                    payload = response.json()
                    payload["fundamental"][field] = value
                    return httpx.Response(200, json=payload)
                return response

            with IntrinioClient(TEST_KEY, transport=httpx.MockTransport(handler)) as provider:
                with self.assertRaises(InvalidResponse):
                    provider.annual_profitability(SECURITY, YEAR)

    def test_partial_response_keeps_input_provenance_but_no_ratio(self):
        def handler(request):
            response = capital_fixture_transport(request)
            if request.url.path.endswith("/standardized_financials"):
                payload = response.json()
                payload["next_page"] = "fixture_cursor"
                return httpx.Response(200, json=payload)
            return response

        with IntrinioClient(TEST_KEY, transport=httpx.MockTransport(handler)) as provider:
            result = provider.annual_profitability(SECURITY, YEAR)
        self.assertFalse(result.income.pagination_complete)
        self.assertTrue(
            all(row.percent is None for row in calculate_capital_returns(result).metrics)
        )


@override_settings(INTRINIO_API_KEY=TEST_KEY)
class CapitalReturnPageTests(SimpleTestCase):
    def setUp(self):
        _request_budget.reset()
        self.addCleanup(_request_budget.reset)
        self.url = reverse("capital_returns", args=[SECURITY])
        self.query = {"fiscal_year": YEAR}

    def response(self, handler=capital_fixture_transport):
        with patch(
            "research.services.IntrinioClient",
            side_effect=lambda key: IntrinioClient(key, transport=httpx.MockTransport(handler)),
        ):
            return self.client.get(self.url, self.query)

    def test_initial_invalid_year_quarter_and_methods_do_not_request_data(self):
        with patch("research.services.IntrinioClient") as provider:
            self.assertContains(
                self.client.get(self.url), "No financial data has been requested yet"
            )
            for query in (
                {"fiscal_year": 1900},
                {"fiscal_year": "2019.5"},
                {"fiscal_year": datetime.now(UTC).year + 2},
                {"fiscal_year": YEAR, "fiscal_period": "Q4"},
                {"fiscal_period": "Q1"},
            ):
                response = self.client.get(self.url, query)
                self.assertEqual(response.status_code, 400)
                self.assertNotContains(response, "capital-returns-panel", status_code=400)
            self.assertEqual(self.client.post(self.url, self.query).status_code, 405)
            self.assertEqual(self.client.head(self.url).status_code, 405)
            self.assertEqual(
                self.client.get(reverse("capital_returns", args=["bad.id"])).status_code, 404
            )
        provider.assert_not_called()

    def test_seven_requests_render_aligned_inputs_ratios_and_version_provenance(self):
        requests = []

        def handler(request):
            requests.append(request)
            return capital_fixture_transport(request)

        response = self.response(handler)
        for text in (
            "10.91%",
            "20.00%",
            "2018-09-30",
            "2018-10-01",
            "2019-09-30",
            "Average balance",
            "1100",
            "600",
            "netincome / totalassets",
            "netincome / totalequity",
            "restated",
            "Filing dates do not establish",
            "not a daily average",
            "common-equity-only",
        ):
            self.assertContains(response, text)
        self.assertEqual(len(requests), 7)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertNotContains(response, TEST_KEY)

    def test_zero_and_loss_display_without_withholding_returns(self):
        for value, expected in ((0, "0.00%"), (-120, "-10.91%")):
            _request_budget.reset()

            def handler(request, value=value):
                response = capital_fixture_transport(request)
                if request.url.path.endswith("/standardized_financials"):
                    payload = response.json()
                    for row in payload["standardized_financials"]:
                        if row["data_tag"]["tag"] == "netincome":
                            row["value"] = value
                    return httpx.Response(200, json=payload)
                return response

            self.assertContains(self.response(handler), expected)

    def test_misalignment_withholds_ratios_and_keeps_dates_visible(self):
        bundle = capital_bundle()
        bundle = change_source(
            bundle,
            "opening_balance",
            fundamental=replace(bundle.opening_balance.fundamental, end_date=date(2018, 9, 29)),
        )
        with patch("research.services.annual_profitability", return_value=bundle):
            response = self.client.get(self.url, self.query)
        self.assertContains(response, "day before income starts")
        self.assertContains(response, "2018-09-29")
        self.assertTrue(
            all(row.percent is None for row in response.context["capital_result"].metrics)
        )

    def test_nonpositive_equity_is_independent_and_no_denominator_fallback(self):
        with patch(
            "research.services.annual_profitability",
            return_value=capital_bundle(equity=("-500", "700")),
        ):
            response = self.client.get(self.url, self.query)
        self.assertContains(response, "10.91%")
        self.assertContains(response, "zero/negative balances are unavailable")
        self.assertIsNone(response.context["capital_result"].metrics[1].percent)

    def test_missing_prior_statement_does_not_substitute_closing_balance(self):
        requests = []

        def handler(request):
            requests.append(request)
            if "/lookup/balance_sheet_statement/2018/" in request.url.path:
                return httpx.Response(404)
            return capital_fixture_transport(request)

        response = self.response(handler)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(len(requests), 4)
        self.assertNotIn("capital_result", response.context)
        self.assertNotContains(response, "capital-returns-panel", status_code=404)

    def test_provider_error_at_last_stage_clears_all_inputs_and_keeps_retry_after(self):
        for status, expected in ((403, 503), (429, 429)):
            _request_budget.reset()
            requests = []

            def handler(request, status=status, requests=requests):
                requests.append(request)
                return (
                    httpx.Response(status, headers={"Retry-After": "41"}, text=TEST_KEY)
                    if len(requests) == 7
                    else capital_fixture_transport(request)
                )

            response = self.response(handler)
            self.assertEqual(response.status_code, expected)
            self.assertEqual(len(requests), 7)
            self.assertNotIn("capital_result", response.context)
            self.assertNotIn("bundle", response.context)
            self.assertNotContains(response, TEST_KEY, status_code=expected)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            if status == 429:
                self.assertEqual(response.headers["Retry-After"], "41")

    def test_shared_budget_caps_second_load_without_new_quota_or_cache(self):
        requests = []

        def handler(request):
            requests.append(request)
            return capital_fixture_transport(request)

        self.assertEqual(self.response(handler).status_code, 200)
        response = self.response(handler)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(len(requests), 10)
        self.assertNotContains(response, "capital-returns-panel", status_code=429)

    @override_settings(INTRINIO_API_KEY="")
    def test_unconfigured_key_uses_existing_safe_error_without_transport(self):
        with patch("research.services.IntrinioClient") as provider:
            response = self.client.get(self.url, self.query)
        self.assertEqual(response.status_code, 503)
        self.assertContains(response, "Intrinio is not configured", status_code=503)
        provider.assert_not_called()

    def test_source_identity_and_metadata_are_escaped(self):
        bundle = capital_bundle()
        bundle = change_source(
            bundle,
            "income",
            fundamental=replace(
                bundle.income.fundamental,
                company=replace(bundle.income.fundamental.company, name="<script>fixture</script>"),
            ),
        )
        with patch("research.services.annual_profitability", return_value=bundle):
            response = self.client.get(self.url, self.query)
        self.assertContains(response, "&lt;script&gt;fixture&lt;/script&gt;")
        self.assertNotContains(response, "<script>fixture</script>")


class CapitalReturnFormTests(SimpleTestCase):
    def test_only_supported_annual_years_are_admitted(self):
        self.assertFalse(CapitalReturnForm().is_bound)
        for value in (1901, YEAR, datetime.now(UTC).year + 1):
            self.assertTrue(CapitalReturnForm({"fiscal_year": value}).is_valid())
        for value in (1900, "2019.5", "", datetime.now(UTC).year + 2):
            self.assertFalse(CapitalReturnForm({"fiscal_year": value}).is_valid())
        self.assertFalse(CapitalReturnForm({"fiscal_year": YEAR, "fiscal_period": "Q1"}).is_valid())

    @override_settings(INTRINIO_API_KEY=TEST_KEY)
    def test_service_spends_the_existing_budget_for_all_seven_requests(self):
        reservations = []
        with (
            patch(
                "research.services.IntrinioClient",
                side_effect=lambda key: IntrinioClient(
                    key, transport=httpx.MockTransport(capital_fixture_transport)
                ),
            ),
            patch(
                "research.services._reserve_request",
                side_effect=lambda client: reservations.append(client),
            ),
        ):
            annual_profitability(SECURITY, YEAR, "fixture-address")
        self.assertEqual(reservations, ["fixture-address"] * 7)
