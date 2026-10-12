"""Independent P/E examples, exact-date validation and four-stage boundaries."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from unittest.mock import patch

import httpx
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from market_data.contracts import AnnualValuationInputs, DailyPrice, FinancialValue, PriceHistory
from market_data.errors import InvalidResponse, ProviderError, ProviderRateLimited
from market_data.intrinio import IntrinioClient
from research.multiple_forms import AnnualMultipleForm
from research.multiples import calculate_annual_multiples
from research.services import _request_budget, annual_valuation
from tests.test_fundamentals import SECURITY, YEAR, fixture_transport
from tests.test_intrinio import TEST_KEY, fixture
from tests.test_profitability import statement

PRICE_DATE = date(2020, 1, 2)


def multiple_bundle(basic="2", diluted="1.5", close="30"):
    income = statement(
        values=tuple(
            FinancialValue(tag, None, "usdpershare", Decimal(value), None)
            for tag, value in (("basiceps", basic), ("dilutedeps", diluted))
        )
    )
    income = replace(income, security=replace(income.security, company_id="com_fixture"))
    prices = PriceHistory(
        income.security,
        (DailyPrice(PRICE_DATE, Decimal(close), Decimal("999"), False),),
        PRICE_DATE,
        PRICE_DATE,
        datetime(2020, 1, 3, tzinfo=UTC),
        True,
    )
    return AnnualValuationInputs(income, prices)


def alter_income(bundle, *, tag=None, **changes):
    source = bundle.income
    if tag is None:
        return replace(bundle, income=replace(source, **changes))
    values = tuple(replace(row, **changes) if row.tag == tag else row for row in source.values)
    return replace(bundle, income=replace(source, values=values))


def multiple_fixture_transport(request):
    """Synthetic source values, deliberately different raw and adjusted closes."""
    if request.url.path.endswith("/prices"):
        payload = fixture("daily_prices.json")
        selected = request.url.params["start_date"]
        payload["stock_prices"] = [
            {
                "date": selected,
                "frequency": "daily",
                "intraperiod": False,
                "close": 30,
                "adj_close": 999,
            }
        ]
        return httpx.Response(200, json=payload)
    response = fixture_transport(request)
    if response.status_code == 200 and request.url.path.endswith("/standardized_financials"):
        payload = response.json()
        for row in payload["standardized_financials"]:
            if row["data_tag"]["tag"] == "basiceps":
                row["value"] = 2
            if row["data_tag"]["tag"] == "dilutedeps":
                row["value"] = 1.5
        return httpx.Response(200, json=payload)
    return response


class AnnualMultipleCalculationTests(SimpleTestCase):
    def result(self, bundle=None, **kwargs):
        return calculate_annual_multiples(
            bundle or multiple_bundle(),
            kwargs.get("price_date", PRICE_DATE),
            basis_confirmed=kwargs.get("basis_confirmed", True),
        )

    def unavailable(self, bundle, text, **kwargs):
        result = self.result(bundle, **kwargs)
        for row in result.metrics:
            self.assertIsNone(row.multiple)
            self.assertIn(text, row.issue)

    def test_hand_calculated_basic_and_diluted_are_multiples_not_percentages(self):
        result = self.result()
        self.assertEqual(tuple(r.multiple for r in result.metrics), (Decimal("15"), Decimal("20")))
        self.assertEqual(tuple(r.eps for r in result.metrics), (Decimal("2"), Decimal("1.5")))
        self.assertEqual(result.raw_close, Decimal("30"))
        self.assertEqual(result.annual_days, 365)

    def test_repeating_and_half_up_values_round_only_final_ratio(self):
        result = self.result(multiple_bundle(basic="3", diluted="2", close="1.005"))
        self.assertEqual(
            tuple(r.multiple for r in result.metrics), (Decimal("0.34"), Decimal("0.50"))
        )
        result = self.result(multiple_bundle(basic="1", close="1.005"))
        self.assertEqual(result.metrics[0].multiple, Decimal("1.01"))

    def test_decimal_context_and_extreme_valid_values_do_not_round_inputs(self):
        bundle = multiple_bundle(basic="1e-18", diluted="1e24", close="1e12")
        with localcontext() as context:
            context.prec, context.Emax, context.Emin = 2, 1, -1
            for signal in context.traps:
                context.traps[signal] = True
            result = self.result(bundle)
        self.assertEqual(result.metrics[0].multiple, Decimal("1e30"))
        self.assertEqual(str(result.metrics[1].multiple), "0.00")

    def test_observed_zero_price_is_a_valid_zero_multiple(self):
        result = self.result(multiple_bundle(close="0"))
        self.assertEqual(result.raw_close, Decimal("0"))
        self.assertEqual(tuple(str(r.multiple) for r in result.metrics), ("0.00", "0.00"))

    def test_zero_and_loss_eps_preserve_observations_without_misleading_pe(self):
        for value in ("0", "-2"):
            result = self.result(multiple_bundle(basic=value))
            self.assertEqual(result.metrics[0].eps, Decimal(value))
            self.assertIsNone(result.metrics[0].multiple)
            self.assertIn("positive EPS", result.metrics[0].issue)
            self.assertEqual(result.metrics[1].multiple, Decimal("20"))

    def test_missing_and_null_eps_are_distinct_and_do_not_fallback(self):
        bundle = multiple_bundle()
        for tag in ("basiceps", "dilutedeps"):
            missing = alter_income(
                bundle, values=tuple(r for r in bundle.income.values if r.tag != tag)
            )
            null = alter_income(bundle, tag=tag, value=None)
            index = 0 if tag == "basiceps" else 1
            self.assertIn("Source tag", self.result(missing).metrics[index].issue)
            self.assertIn("Source value", self.result(null).metrics[index].issue)
            self.assertIsNotNone(self.result(null).metrics[1 - index].multiple)

    def test_eps_units_are_explicit_not_inferred_from_listing_currency(self):
        for unit in (None, "usd", "USD", "shares", "eurpershare", "percentage"):
            result = self.result(alter_income(multiple_bundle(), tag="basiceps", unit=unit))
            self.assertIsNone(result.metrics[0].multiple)
            self.assertIn("usdpershare", result.metrics[0].issue)
            self.assertEqual(result.metrics[1].multiple, Decimal("20"))

    def test_unsupported_nonfinite_or_expansive_eps_cannot_calculate(self):
        for value in (
            True,
            1,
            1.0,
            "1",
            Decimal("NaN"),
            Decimal("sNaN"),
            Decimal("Infinity"),
            Decimal("1e25"),
            Decimal("1e-19"),
        ):
            result = self.result(alter_income(multiple_bundle(), tag="basiceps", value=value))
            self.assertIsNone(result.metrics[0].multiple)
            self.assertIn("finite financial number", result.metrics[0].issue)

    def test_company_association_does_not_replace_explicit_basis_confirmation(self):
        for confirmation in (False, None, 1, "true"):
            self.unavailable(multiple_bundle(), "share class", basis_confirmed=confirmation)

    def test_adjusted_close_never_replaces_missing_raw_close(self):
        bundle = multiple_bundle()
        prices = replace(
            bundle.prices, observations=(replace(bundle.prices.observations[0], close=None),)
        )
        self.unavailable(replace(bundle, prices=prices), "raw USD close")
        self.assertEqual(self.result().raw_close, Decimal("30"))

    def test_uncertain_intraperiod_or_partial_prices_are_unavailable(self):
        bundle = multiple_bundle()
        for flag in (None, True):
            prices = replace(
                bundle.prices,
                observations=(replace(bundle.prices.observations[0], intraperiod=flag),),
            )
            self.unavailable(replace(bundle, prices=prices), "confirmed raw USD close")
        self.unavailable(
            replace(bundle, prices=replace(bundle.prices, pagination_complete=False)), "complete"
        )

    def test_empty_duplicate_or_wrong_date_closes_never_fallback(self):
        bundle = multiple_bundle()
        observation = bundle.prices.observations[0]
        for observations in (
            (),
            (observation, observation),
            (replace(observation, date=PRICE_DATE - timedelta(days=1)),),
            (replace(observation, date=datetime(2020, 1, 2)),),
        ):
            self.unavailable(
                replace(bundle, prices=replace(bundle.prices, observations=observations)),
                "exact date",
            )

    def test_price_reference_identity_currency_venue_and_company_must_match(self):
        bundle = multiple_bundle()
        for changes in (
            {"id": "sec_other"},
            {"currency": "EUR"},
            {"currency": None},
            {"exchange_mic": "XNAS"},
            {"exchange_mic": None},
            {"company_id": "com_other"},
        ):
            prices = replace(bundle.prices, security=replace(bundle.prices.security, **changes))
            self.unavailable(replace(bundle, prices=prices), "instrument and venue")
        for changes in ({"currency": "EUR"}, {"currency": None}, {"exchange_mic": None}):
            self.unavailable(
                alter_income(bundle, security=replace(bundle.income.security, **changes)),
                "instrument and venue",
            )

    def test_optional_missing_company_in_price_summary_is_not_inferred(self):
        bundle = multiple_bundle()
        prices = replace(bundle.prices, security=replace(bundle.prices.security, company_id=None))
        self.assertEqual(
            self.result(replace(bundle, prices=prices)).metrics[0].multiple, Decimal("15")
        )

    def test_price_request_bounds_must_be_the_exact_selected_day(self):
        bundle = multiple_bundle()
        for changes in (
            {"start_date": PRICE_DATE - timedelta(days=1)},
            {"end_date": PRICE_DATE + timedelta(days=1)},
        ):
            self.unavailable(
                replace(bundle, prices=replace(bundle.prices, **changes)), "exact date"
            )

    def test_price_retrieval_requires_timezone_and_cannot_predate_observation(self):
        bundle = multiple_bundle()
        for time in (
            None,
            date(2020, 1, 3),
            datetime(2020, 1, 3),
            datetime(2020, 1, 1, tzinfo=UTC),
        ):
            self.unavailable(
                replace(bundle, prices=replace(bundle.prices, retrieved_at=time)), "confirmed"
            )

    def test_unsupported_negative_or_out_of_bounds_raw_close_withholds_both(self):
        bundle = multiple_bundle()
        for value in (
            True,
            1.0,
            Decimal("-1"),
            Decimal("NaN"),
            Decimal("Infinity"),
            Decimal("1e13"),
            Decimal("1e-19"),
        ):
            prices = replace(
                bundle.prices, observations=(replace(bundle.prices.observations[0], close=value),)
            )
            self.unavailable(replace(bundle, prices=prices), "confirmed")

    def test_only_annual_income_with_explicit_integer_fiscal_label_is_supported(self):
        bundle = multiple_bundle()
        for changes in (
            {"statement_code": "balance_sheet_statement"},
            {"fiscal_period": "Q4"},
            {"fiscal_period": "TTM"},
            {"fiscal_year": True},
            {"fiscal_year": "2019"},
        ):
            self.unavailable(
                alter_income(bundle, fundamental=replace(bundle.income.fundamental, **changes)),
                "annual FY",
            )

    def test_missing_company_or_wrong_statement_association_is_unavailable(self):
        bundle = multiple_bundle()
        for value in (None, "com_other"):
            self.unavailable(
                alter_income(bundle, security=replace(bundle.income.security, company_id=value)),
                "company identity",
            )

    def test_missing_timestamp_reversed_and_stub_period_dates_are_unavailable(self):
        bundle = multiple_bundle()
        for changes in (
            {"start_date": None},
            {"end_date": None},
            {"start_date": datetime(2018, 10, 1)},
            {"start_date": date(2019, 9, 30)},
            {"end_date": date(2018, 9, 30)},
        ):
            self.unavailable(
                alter_income(bundle, fundamental=replace(bundle.income.fundamental, **changes)),
                "date-only",
            )
        self.unavailable(
            alter_income(
                bundle, fundamental=replace(bundle.income.fundamental, start_date=date(2019, 4, 1))
            ),
            "stub periods",
        )

    def test_leap_and_53_week_years_are_retained_without_annualization(self):
        bundle = multiple_bundle()
        for start, end, days in (
            (date(2018, 9, 23), date(2019, 9, 28), 371),
            (date(2016, 1, 1), date(2016, 12, 31), 366),
        ):
            result = self.result(
                alter_income(
                    bundle,
                    fundamental=replace(bundle.income.fundamental, start_date=start, end_date=end),
                )
            )
            self.assertEqual(result.annual_days, days)
            self.assertEqual(result.metrics[0].multiple, Decimal("15"))

    def test_price_cannot_precede_income_end_but_matching_date_is_allowed(self):
        bundle = multiple_bundle()
        self.unavailable(bundle, "on or after", price_date=date(2019, 9, 29))
        selected = bundle.income.fundamental.end_date
        prices = replace(
            bundle.prices,
            start_date=selected,
            end_date=selected,
            observations=(replace(bundle.prices.observations[0], date=selected),),
        )
        self.assertEqual(
            self.result(replace(bundle, prices=prices), price_date=selected).metrics[0].multiple,
            Decimal("15"),
        )

    def test_partial_statement_or_duplicate_tags_withhold_both(self):
        bundle = multiple_bundle()
        self.unavailable(alter_income(bundle, pagination_complete=False), "must be complete")
        self.unavailable(
            alter_income(bundle, values=(*bundle.income.values, bundle.income.values[0])),
            "Duplicate",
        )

    def test_known_classifications_supported_unknown_is_unavailable(self):
        bundle = multiple_bundle()
        for kind in ("reported", "calculated", "restated"):
            result = self.result(
                alter_income(bundle, fundamental=replace(bundle.income.fundamental, type=kind))
            )
            self.assertEqual(result.metrics[0].multiple, Decimal("15"))
        self.unavailable(
            alter_income(bundle, fundamental=replace(bundle.income.fundamental, type=None)),
            "classification",
        )


class AnnualMultipleAdapterTests(SimpleTestCase):
    def call(self, handler, **kwargs):
        with IntrinioClient(TEST_KEY, transport=httpx.MockTransport(handler)) as provider:
            return provider.annual_valuation(SECURITY, YEAR, PRICE_DATE, **kwargs)

    def test_four_requests_one_reference_and_one_exact_date_page_reserve_each(self):
        requests, reserved = [], []

        def handler(request):
            requests.append(request)
            self.assertEqual(request.url.host, "api-v2.intrinio.com")
            self.assertEqual(request.url.params["api_key"], TEST_KEY)
            return multiple_fixture_transport(request)

        result = self.call(handler, before_request=lambda: reserved.append(True))
        self.assertEqual(len(requests), 4)
        self.assertEqual(len(reserved), 4)
        self.assertEqual(sum(r.url.path == "/securities/" + SECURITY for r in requests), 1)
        price = requests[-1]
        self.assertEqual(price.url.params["start_date"], PRICE_DATE.isoformat())
        self.assertEqual(price.url.params["end_date"], PRICE_DATE.isoformat())
        self.assertNotIn("next_page", price.url.params)
        self.assertEqual(result.income.fundamental.fiscal_year, YEAR)

    def test_invalid_security_year_or_date_never_spends_transport(self):
        handler = patch("market_data.intrinio.IntrinioClient._request_json")
        with handler as request, IntrinioClient(TEST_KEY) as provider:
            for security, year, selected in (
                ("bad.id", YEAR, PRICE_DATE),
                (SECURITY, True, PRICE_DATE),
                (SECURITY, YEAR, "2020-01-02"),
                (SECURITY, YEAR, datetime.now(UTC).date() + timedelta(days=1)),
            ):
                with self.assertRaises(ValueError):
                    provider.annual_valuation(security, year, selected)
            request.assert_not_called()

    def test_failures_at_every_stage_stop_without_retry_or_fallback(self):
        for stage in range(1, 5):
            for status in (403, 404, 429):
                requests = []

                def handler(request, stage=stage, status=status, requests=requests):
                    requests.append(request)
                    return (
                        httpx.Response(status, text=TEST_KEY)
                        if len(requests) == stage
                        else multiple_fixture_transport(request)
                    )

                with self.assertRaises(ProviderError):
                    self.call(handler)
                self.assertEqual(len(requests), stage)

    def test_quota_denial_before_each_stage_sends_no_denied_request(self):
        for stage in range(1, 5):
            requests, reserved = [], []

            def reserve(reserved=reserved, stage=stage):
                reserved.append(True)
                if len(reserved) == stage:
                    raise ProviderRateLimited(42)

            def handler(request, requests=requests):
                requests.append(request)
                return multiple_fixture_transport(request)

            with self.assertRaises(ProviderRateLimited):
                self.call(handler, before_request=reserve)
            self.assertEqual(len(requests), stage - 1)

    def test_lookup_and_values_cannot_mix_company_period_id_or_dates(self):
        for changes in (
            {"id": "fun_other"},
            {"fiscal_year": 2018},
            {"fiscal_period": "Q4"},
            {"end_date": "2019-09-29"},
            {"type": "restated"},
        ):

            def handler(request, changes=changes):
                response = multiple_fixture_transport(request)
                if request.url.path.endswith("/standardized_financials"):
                    payload = response.json()
                    payload["fundamental"].update(changes)
                    return httpx.Response(200, json=payload)
                return response

            with self.assertRaises(InvalidResponse):
                self.call(handler)


@override_settings(INTRINIO_API_KEY=TEST_KEY)
class AnnualMultiplePageTests(SimpleTestCase):
    def setUp(self):
        _request_budget.reset()
        self.addCleanup(_request_budget.reset)
        self.url = reverse("annual_multiples", args=[SECURITY])
        self.query = {
            "fiscal_year": YEAR,
            "price_date": PRICE_DATE.isoformat(),
            "basis_confirmed": "on",
        }

    def response(self, handler=multiple_fixture_transport, query=None):
        with patch(
            "research.services.IntrinioClient",
            side_effect=lambda key: IntrinioClient(key, transport=httpx.MockTransport(handler)),
        ):
            return self.client.get(self.url, self.query if query is None else query)

    def test_initial_invalid_inputs_method_and_id_make_no_requests(self):
        with patch("research.services.IntrinioClient") as provider:
            initial = self.client.get(self.url)
            self.assertContains(initial, "No financial data or prices have been requested yet")
            self.assertNotContains(initial, "checked")
            for query in (
                {"fiscal_year": YEAR},
                {**self.query, "basis_confirmed": ""},
                {**self.query, "fiscal_period": "TTM"},
                {**self.query, "fiscal_year": "2019.5"},
                {**self.query, "price_date": "invalid"},
                {
                    **self.query,
                    "price_date": (datetime.now(UTC).date() + timedelta(days=1)).isoformat(),
                },
            ):
                self.assertNotContains(
                    self.client.get(self.url, query), "multiples-panel", status_code=400
                )
            self.assertEqual(self.client.post(self.url, self.query).status_code, 405)
            self.assertEqual(self.client.head(self.url).status_code, 405)
            self.assertEqual(
                self.client.get(reverse("annual_multiples", args=["bad.id"])).status_code, 404
            )
        provider.assert_not_called()

    def test_four_requests_render_both_pe_dates_assumptions_and_sources(self):
        requests = []

        def handler(request):
            requests.append(request)
            return multiple_fixture_transport(request)

        response = self.response(handler)
        for text in (
            "15.00×",
            "20.00×",
            "2019 FY P/E",
            "2018-10-01",
            "2019-09-30",
            "2020-01-02",
            "Basic FY P/E",
            "Diluted FY P/E",
            "not independently verified",
            "basiceps",
            "dilutedeps",
            "Classification",
            "SEC filing",
            "Provider update",
            "First calculable",
            "Retrieved",
            "historical-as-known",
            "not prove this exact EPS version",
            "positive selected-FY EPS",
        ):
            self.assertContains(response, text)
        self.assertEqual(len(requests), 4)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertNotContains(response, TEST_KEY)

    def test_negative_or_null_eps_does_not_replace_with_other_measure(self):
        for value in (None, -2, 0):
            _request_budget.reset()

            def handler(request, value=value):
                response = multiple_fixture_transport(request)
                if request.url.path.endswith("/standardized_financials"):
                    payload = response.json()
                    for row in payload["standardized_financials"]:
                        if row["data_tag"]["tag"] == "basiceps":
                            row["value"] = value
                    return httpx.Response(200, json=payload)
                return response

            response = self.response(handler)
            self.assertIsNone(response.context["multiples"].metrics[0].multiple)
            self.assertContains(response, "20.00×")

    def test_missing_or_uncertain_close_has_no_adjusted_or_previous_date_fallback(self):
        for observations in (
            [],
            [
                {
                    "date": "2020-01-02",
                    "frequency": "daily",
                    "intraperiod": None,
                    "close": 30,
                    "adj_close": 999,
                }
            ],
        ):
            _request_budget.reset()
            requests = []

            def handler(request, observations=observations, requests=requests):
                requests.append(request)
                response = multiple_fixture_transport(request)
                if request.url.path.endswith("/prices"):
                    payload = response.json()
                    payload["stock_prices"] = observations
                    return httpx.Response(200, json=payload)
                return response

            response = self.response(handler)
            self.assertContains(response, "No complete, confirmed raw USD close")
            self.assertNotContains(response, "15.00×")
            self.assertEqual(len(requests), 4)

    def test_partial_price_response_does_not_follow_cursor(self):
        requests = []

        def handler(request):
            requests.append(request)
            response = multiple_fixture_transport(request)
            if request.url.path.endswith("/prices"):
                payload = response.json()
                payload["next_page"] = "fixture_cursor"
                return httpx.Response(200, json=payload)
            return response

        response = self.response(handler)
        self.assertContains(response, "Partial price response")
        self.assertEqual(len(requests), 4)
        self.assertIsNone(response.context["multiples"].metrics[0].multiple)

    def test_price_before_income_end_and_unknown_statement_classification_withhold(self):
        for query, classification in (
            ({**self.query, "price_date": "2019-09-29"}, "reported"),
            (self.query, None),
        ):
            _request_budget.reset()

            def handler(request, classification=classification):
                response = multiple_fixture_transport(request)
                if "/fundamentals/lookup/" in request.url.path or request.url.path.endswith(
                    "/standardized_financials"
                ):
                    payload = response.json()
                    period = payload["fundamental"] if "fundamental" in payload else payload
                    period["type"] = classification
                    return httpx.Response(200, json=payload)
                return response

            response = self.response(handler, query)
            self.assertTrue(all(r.multiple is None for r in response.context["multiples"].metrics))

    def test_final_stage_errors_clear_loaded_context_and_redact_provider_text(self):
        for status, expected in ((403, 503), (404, 404), (429, 429)):
            _request_budget.reset()
            requests = []

            def handler(request, status=status, requests=requests):
                requests.append(request)
                return (
                    httpx.Response(status, text=TEST_KEY, headers={"Retry-After": "37"})
                    if len(requests) == 4
                    else multiple_fixture_transport(request)
                )

            response = self.response(handler)
            self.assertEqual(response.status_code, expected)
            self.assertNotIn("bundle", response.context)
            self.assertNotIn("multiples", response.context)
            self.assertNotContains(response, "multiples-panel", status_code=expected)
            self.assertNotContains(response, TEST_KEY, status_code=expected)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            if status == 429:
                self.assertEqual(response.headers["Retry-After"], "37")

    def test_shared_budget_caps_repeated_loads_at_ten_http_requests(self):
        requests = []

        def handler(request):
            requests.append(request)
            return multiple_fixture_transport(request)

        self.assertEqual(self.response(handler).status_code, 200)
        self.assertEqual(self.response(handler).status_code, 200)
        self.assertEqual(self.response(handler).status_code, 429)
        self.assertEqual(len(requests), 10)

    @override_settings(INTRINIO_API_KEY="")
    def test_missing_key_does_not_construct_transport(self):
        with patch("research.services.IntrinioClient") as provider:
            response = self.client.get(self.url, self.query)
        self.assertContains(response, "Intrinio is not configured", status_code=503)
        provider.assert_not_called()

    def test_supplied_text_escaped_and_unexpected_failure_is_redacted(self):
        bundle = multiple_bundle()
        income = replace(
            bundle.income,
            fundamental=replace(
                bundle.income.fundamental,
                company=replace(bundle.income.fundamental.company, name="<script>fixture</script>"),
            ),
        )
        with patch(
            "research.services.annual_valuation", return_value=replace(bundle, income=income)
        ):
            response = self.client.get(self.url, self.query)
        self.assertContains(response, "&lt;script&gt;fixture&lt;/script&gt;")
        self.assertNotContains(response, "<script>fixture</script>")
        with (
            patch("research.services.annual_valuation", side_effect=RuntimeError(TEST_KEY)),
            self.assertLogs("research", level="ERROR") as logs,
        ):
            response = self.client.get(self.url, self.query)
        self.assertNotContains(response, TEST_KEY, status_code=503)
        self.assertNotIn(TEST_KEY, "".join(logs.output))


class AnnualMultipleFormServiceTests(SimpleTestCase):
    def test_explicit_fy_date_and_confirmation_validation(self):
        query = {"fiscal_year": YEAR, "price_date": PRICE_DATE.isoformat(), "basis_confirmed": "on"}
        self.assertFalse(AnnualMultipleForm().is_bound)
        self.assertTrue(AnnualMultipleForm(query).is_valid())
        for changes in (
            {"fiscal_period": "Q1"},
            {"basis_confirmed": False},
            {"price_date": "1899-12-31"},
            {"fiscal_year": datetime.now(UTC).year + 2},
        ):
            self.assertFalse(AnnualMultipleForm({**query, **changes}).is_valid())

    @override_settings(INTRINIO_API_KEY=TEST_KEY)
    def test_service_reserves_existing_budget_for_each_of_four_requests(self):
        reservations = []
        with (
            patch(
                "research.services.IntrinioClient",
                side_effect=lambda key: IntrinioClient(
                    key, transport=httpx.MockTransport(multiple_fixture_transport)
                ),
            ),
            patch(
                "research.services._reserve_request",
                side_effect=lambda client: reservations.append(client),
            ),
        ):
            annual_valuation(SECURITY, YEAR, PRICE_DATE, "fixture-address")
        self.assertEqual(reservations, ["fixture-address"] * 4)
