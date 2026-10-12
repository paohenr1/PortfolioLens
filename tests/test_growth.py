"""Independent annual growth examples and five-stage provider/page boundaries."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal, localcontext
from unittest.mock import patch

import httpx
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from market_data.contracts import AnnualGrowthStatements, Company
from market_data.errors import InvalidResponse, ProviderError, ProviderRateLimited
from market_data.intrinio import IntrinioClient
from research.financial_math import exact_change
from research.growth import calculate_annual_growth
from research.growth_forms import AnnualGrowthForm
from research.services import _request_budget, annual_growth
from tests.test_capital_returns import capital_fixture_transport, change_source
from tests.test_fundamentals import SECURITY, YEAR
from tests.test_intrinio import TEST_KEY
from tests.test_profitability import statement


def growth_bundle(prior_revenue="800", current_revenue="1000", prior_net="100", current_net="120"):
    current = statement(revenue=current_revenue, net=current_net)
    current = replace(current, security=replace(current.security, company_id="com_fixture"))
    prior = replace(
        statement(revenue=prior_revenue, net=prior_net),
        security=current.security,
        fundamental=replace(
            current.fundamental,
            id="fun_prior",
            fiscal_year=2018,
            start_date=date(2017, 10, 1),
            end_date=date(2018, 9, 30),
        ),
    )
    return AnnualGrowthStatements(prior, current)


def growth_fixture_transport(request):
    """Only synthetic test data. The production adapter never imports this."""
    response = capital_fixture_transport(request)
    if response.status_code == 200 and request.url.path.endswith("/standardized_financials"):
        payload = response.json()
        if payload["fundamental"]["fiscal_year"] == 2018:
            for row in payload["standardized_financials"]:
                if row["data_tag"]["tag"] == "totalrevenue":
                    row["value"] = 800
                if row["data_tag"]["tag"] == "netincome":
                    row["value"] = 100
        return httpx.Response(200, json=payload)
    return response


class AnnualGrowthCalculationTests(SimpleTestCase):
    def result(self, bundle=None):
        return calculate_annual_growth(bundle or growth_bundle())

    def unavailable(self, bundle, text):
        result = self.result(bundle)
        for row in result.metrics:
            self.assertIsNone(row.percent)
            self.assertIsNone(row.change)
            self.assertIn(text, row.issue)

    def test_hand_calculated_revenue_and_net_income_growth(self):
        result = self.result()
        self.assertEqual(
            tuple(row.percent for row in result.metrics), (Decimal("25.00"), Decimal("20.00"))
        )
        self.assertEqual(
            tuple(row.change for row in result.metrics), (Decimal("200"), Decimal("20"))
        )
        self.assertEqual((result.prior_days, result.current_days), (365, 365))
        self.assertIsNone(result.alignment_issue)

    def test_unchanged_positive_and_decreased_values(self):
        result = self.result(growth_bundle(current_revenue="800", current_net="80"))
        self.assertEqual(
            tuple(row.percent for row in result.metrics), (Decimal("0.00"), Decimal("-20.00"))
        )
        self.assertEqual(tuple(row.movement for row in result.metrics), ("Unchanged", "Decreased"))

    def test_positive_prior_current_zero_is_minus_one_hundred(self):
        result = self.result(growth_bundle(current_revenue="0", current_net="0"))
        self.assertEqual(tuple(row.percent for row in result.metrics), (Decimal("-100.00"),) * 2)
        self.assertEqual(result.metrics[1].movement, "Profit to break-even")

    def test_profit_to_loss_has_signed_growth_below_minus_one_hundred(self):
        row = self.result(growth_bundle(current_net="-20")).metrics[1]
        self.assertEqual(row.percent, Decimal("-120.00"))
        self.assertEqual(row.change, Decimal("-120"))
        self.assertEqual(row.movement, "Profit to loss")

    def test_zero_base_preserves_change_but_percentage_is_undefined(self):
        result = self.result(growth_bundle(prior_revenue="0", prior_net="0", current_net="50"))
        self.assertEqual(
            tuple(row.change for row in result.metrics), (Decimal("1000"), Decimal("50"))
        )
        self.assertTrue(all(row.percent is None for row in result.metrics))
        self.assertEqual(result.metrics[1].movement, "Break-even to profit")
        self.assertIn("positive prior value", result.metrics[0].issue)

    def test_zero_to_zero_and_break_even_to_loss_are_not_growth_percentages(self):
        for current, movement in (("0", "Unchanged"), ("-50", "Break-even to loss")):
            row = self.result(growth_bundle(prior_net="0", current_net=current)).metrics[1]
            self.assertIsNone(row.percent)
            self.assertEqual(row.movement, movement)
            self.assertEqual(row.change, Decimal(current))

    def test_negative_base_profit_and_break_even_transitions(self):
        for current, delta, movement in (
            ("50", "150", "Loss to profit"),
            ("0", "100", "Loss to break-even"),
        ):
            row = self.result(growth_bundle(prior_net="-100", current_net=current)).metrics[1]
            self.assertIsNone(row.percent)
            self.assertEqual(row.change, Decimal(delta))
            self.assertEqual(row.movement, movement)

    def test_losses_narrow_widen_or_stay_unchanged_without_percent_growth(self):
        for current, delta, movement in (
            ("-50", "50", "Loss narrowed"),
            ("-150", "-50", "Loss widened"),
            ("-100", "0", "Loss unchanged"),
        ):
            row = self.result(growth_bundle(prior_net="-100", current_net=current)).metrics[1]
            self.assertIsNone(row.percent)
            self.assertEqual(row.change, Decimal(delta))
            self.assertEqual(row.movement, movement)

    def test_negative_revenue_base_also_withholds_percentage(self):
        row = self.result(growth_bundle(prior_revenue="-800")).metrics[0]
        self.assertIsNone(row.percent)
        self.assertEqual(row.change, Decimal("1800"))
        self.assertEqual(row.movement, "Increased")

    def test_repeating_and_half_up_both_signs_round_only_final_percentage(self):
        row = self.result(growth_bundle(prior_net="3", current_net="4")).metrics[1]
        self.assertEqual(row.percent, Decimal("33.33"))
        for current, percent in (("101.005", "1.01"), ("98.995", "-1.01")):
            row = self.result(growth_bundle(current_net=current)).metrics[1]
            self.assertEqual(row.percent, Decimal(percent))

    def test_tiny_negative_change_keeps_exact_dollars_and_positive_display_zero(self):
        row = self.result(growth_bundle(current_net="99.999999")).metrics[1]
        self.assertEqual(str(row.percent), "0.00")
        self.assertEqual(row.change, Decimal("-0.000001"))

    def test_exact_large_small_change_and_context_independence(self):
        bundle = growth_bundle(prior_net="1e24", current_net="1e-18")
        with localcontext() as context:
            context.prec, context.Emax, context.Emin = 2, 1, -1
            for signal in context.traps:
                context.traps[signal] = True
            row = self.result(bundle).metrics[1]
        self.assertEqual(row.change, Decimal("-999999999999999999999999.999999999999999999"))
        self.assertEqual(row.percent, Decimal("-100.00"))
        self.assertEqual(exact_change(Decimal("1e24"), Decimal("-1e24")), Decimal("-2e24"))

    def test_missing_and_null_sources_only_disable_the_affected_metric(self):
        source = growth_bundle()
        for scope in ("prior", "current"):
            altered = change_source(source, scope, tag="netincome", value=None)
            result = self.result(altered)
            self.assertIn("source value netincome", result.metrics[1].issue)
            self.assertEqual(result.metrics[0].percent, Decimal("25.00"))
            current = getattr(source, scope)
            altered = change_source(
                source, scope, values=tuple(row for row in current.values if row.tag != "netincome")
            )
            self.assertIn("source tag netincome", self.result(altered).metrics[1].issue)

    def test_nonfinite_float_boolean_or_out_of_bounds_values_cannot_compare(self):
        for scope in ("prior", "current"):
            for value in (
                True,
                100,
                100.0,
                "100",
                Decimal("NaN"),
                Decimal("sNaN"),
                Decimal("Infinity"),
                Decimal("1e25"),
                Decimal("1e-19"),
            ):
                row = self.result(
                    change_source(growth_bundle(), scope, tag="netincome", value=value)
                ).metrics[1]
                self.assertIsNone(row.change)
                self.assertIsNone(row.percent)
                self.assertIn("finite financial number", row.issue)

    def test_units_must_be_explicit_usd_in_both_periods(self):
        for scope in ("prior", "current"):
            for unit in (None, "eur", "USD", "usdpershare", "percentage", "shares", "usd_millions"):
                result = self.result(
                    change_source(growth_bundle(), scope, tag="totalrevenue", unit=unit)
                )
                self.assertIn("explicit provider unit of usd", result.metrics[0].issue)
                self.assertIsNone(result.metrics[0].change)
                self.assertEqual(result.metrics[1].percent, Decimal("20.00"))

    def test_listing_currency_is_not_used_for_statement_units(self):
        bundle = growth_bundle()
        for scope in ("prior", "current"):
            bundle = change_source(
                bundle, scope, security=replace(getattr(bundle, scope).security, currency="EUR")
            )
        self.assertEqual(self.result(bundle).metrics[0].percent, Decimal("25.00"))

    def test_company_and_instrument_identity_must_match(self):
        for scope in ("prior", "current"):
            bundle = growth_bundle()
            source = getattr(bundle, scope)
            self.unavailable(
                change_source(
                    bundle,
                    scope,
                    fundamental=replace(
                        source.fundamental, company=Company("com_other", None, None)
                    ),
                ),
                "same verified",
            )
            self.unavailable(
                change_source(bundle, scope, security=replace(source.security, company_id=None)),
                "same verified",
            )
        bundle = growth_bundle()
        self.unavailable(
            change_source(bundle, "prior", security=replace(bundle.prior.security, id="sec_other")),
            "same verified",
        )

    def test_only_consecutive_fy_income_statements_are_compared(self):
        bundle = growth_bundle()
        for scope, changes in (
            ("prior", {"statement_code": "balance_sheet_statement"}),
            ("current", {"fiscal_period": "Q4"}),
            ("prior", {"fiscal_period": "TTM"}),
            ("prior", {"fiscal_year": 2017}),
            ("current", {"fiscal_year": 2020}),
            ("current", {"fiscal_year": True}),
        ):
            source = getattr(bundle, scope)
            self.unavailable(
                change_source(bundle, scope, fundamental=replace(source.fundamental, **changes)),
                "consecutive annual FY",
            )

    def test_missing_reversed_same_day_or_timestamp_dates_are_unavailable(self):
        for scope in ("prior", "current"):
            bundle = growth_bundle()
            period = getattr(bundle, scope).fundamental
            for start, end in (
                (None, period.end_date),
                (period.start_date, None),
                (period.end_date, period.start_date),
                (period.end_date, period.end_date),
                (datetime(2018, 10, 1), period.end_date),
            ):
                self.unavailable(
                    change_source(
                        bundle, scope, fundamental=replace(period, start_date=start, end_date=end)
                    ),
                    "valid supplied date-only",
                )

    def test_periods_must_be_adjacent_without_gap_or_overlap(self):
        bundle = growth_bundle()
        for start in (date(2018, 9, 30), date(2018, 10, 2)):
            self.unavailable(
                change_source(
                    bundle,
                    "current",
                    fundamental=replace(bundle.current.fundamental, start_date=start),
                ),
                "gap or overlap",
            )

    def test_stub_period_is_not_treated_as_full_year_growth(self):
        bundle = growth_bundle()
        self.unavailable(
            change_source(
                bundle,
                "prior",
                fundamental=replace(bundle.prior.fundamental, start_date=date(2018, 4, 1)),
            ),
            "stub periods",
        )

    def test_week_based_years_allow_seven_day_length_difference(self):
        bundle = growth_bundle()
        bundle = change_source(
            bundle,
            "prior",
            fundamental=replace(bundle.prior.fundamental, end_date=date(2018, 9, 29)),
        )
        bundle = change_source(
            bundle,
            "current",
            fundamental=replace(
                bundle.current.fundamental, start_date=date(2018, 9, 30), end_date=date(2019, 10, 5)
            ),
        )
        result = self.result(bundle)
        self.assertEqual((result.prior_days, result.current_days), (364, 371))
        self.assertEqual(result.metrics[0].percent, Decimal("25.00"))

    def test_length_difference_above_seven_days_is_unavailable(self):
        bundle = growth_bundle()
        self.unavailable(
            change_source(
                bundle,
                "current",
                fundamental=replace(bundle.current.fundamental, end_date=date(2019, 10, 8)),
            ),
            "at most seven days",
        )

    def test_leap_day_is_retained_without_per_day_or_year_adjustment(self):
        bundle = growth_bundle()
        bundle = change_source(
            bundle,
            "prior",
            fundamental=replace(
                bundle.prior.fundamental,
                fiscal_year=2019,
                start_date=date(2018, 3, 1),
                end_date=date(2019, 2, 28),
            ),
        )
        bundle = change_source(
            bundle,
            "current",
            fundamental=replace(
                bundle.current.fundamental,
                fiscal_year=2020,
                start_date=date(2019, 3, 1),
                end_date=date(2020, 2, 29),
            ),
        )
        result = self.result(bundle)
        self.assertEqual((result.prior_days, result.current_days), (365, 366))
        self.assertEqual(result.metrics[1].percent, Decimal("20.00"))

    def test_partial_and_duplicate_tags_withhold_entire_comparison(self):
        for scope in ("prior", "current"):
            bundle = growth_bundle()
            self.unavailable(
                change_source(bundle, scope, pagination_complete=False), "must be complete"
            )
            source = getattr(bundle, scope)
            self.unavailable(
                change_source(bundle, scope, values=(*source.values, source.values[0])),
                "Duplicate source tags",
            )

    def test_known_classifications_mixed_versions_warn_unknown_withholds(self):
        bundle = growth_bundle()
        altered = change_source(
            bundle, "prior", fundamental=replace(bundle.prior.fundamental, type="restated")
        )
        result = self.result(altered)
        self.assertEqual(result.metrics[0].percent, Decimal("25.00"))
        self.assertIn("classifications differ", result.version_warning)
        self.assertIsNone(self.result().version_warning)
        self.unavailable(
            change_source(
                bundle, "current", fundamental=replace(bundle.current.fundamental, type=None)
            ),
            "known reported/calculated/restated",
        )


class AnnualGrowthAdapterTests(SimpleTestCase):
    def test_five_requests_reuse_one_identity_and_reserve_each_stage(self):
        requests, reservations = [], []

        def handler(request):
            requests.append(request)
            return growth_fixture_transport(request)

        with IntrinioClient(TEST_KEY, transport=httpx.MockTransport(handler)) as provider:
            bundle = provider.annual_growth(
                SECURITY, YEAR, before_request=lambda: reservations.append(True)
            )
        self.assertEqual((len(requests), len(reservations)), (5, 5))
        self.assertEqual(
            sum(request.url.path.startswith("/securities/") for request in requests), 1
        )
        self.assertEqual(
            (bundle.prior.fundamental.fiscal_year, bundle.current.fundamental.fiscal_year),
            (2018, 2019),
        )
        self.assertEqual(calculate_annual_growth(bundle).metrics[0].percent, Decimal("25.00"))

    def test_invalid_request_never_spends_transport(self):
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
                    provider.annual_growth(security, year)
        self.assertEqual(requests, [])

    def test_provider_failure_at_each_stage_stops_without_retry_or_fallback(self):
        for stage in range(1, 6):
            for status in (403, 429, 404):
                requests = []

                def handler(request, stage=stage, status=status, requests=requests):
                    requests.append(request)
                    return (
                        httpx.Response(status, headers={"Retry-After": "60"}, text=TEST_KEY)
                        if len(requests) == stage
                        else growth_fixture_transport(request)
                    )

                with IntrinioClient(TEST_KEY, transport=httpx.MockTransport(handler)) as provider:
                    with self.assertRaises(ProviderError):
                        provider.annual_growth(SECURITY, YEAR)
                self.assertEqual(len(requests), stage)

    def test_quota_denial_before_any_stage_stops_that_request(self):
        for stage in range(1, 6):
            requests, reservations = [], []

            def reserve(stage=stage, reservations=reservations):
                reservations.append(True)
                if len(reservations) == stage:
                    raise ProviderRateLimited(19)

            def handler(request, requests=requests):
                requests.append(request)
                return growth_fixture_transport(request)

            with IntrinioClient(TEST_KEY, transport=httpx.MockTransport(handler)) as provider:
                with self.assertRaises(ProviderRateLimited):
                    provider.annual_growth(SECURITY, YEAR, before_request=reserve)
            self.assertEqual(len(requests), stage - 1)

    def test_lookup_value_company_period_or_dates_cannot_be_mixed(self):
        for field, value in (
            ("company", {"id": "com_other"}),
            ("fiscal_year", 2020),
            ("fiscal_period", "Q4"),
            ("end_date", "2019-09-29"),
        ):

            def handler(request, field=field, value=value):
                response = growth_fixture_transport(request)
                if request.url.path.endswith("/standardized_financials"):
                    payload = response.json()
                    payload["fundamental"][field] = value
                    return httpx.Response(200, json=payload)
                return response

            with IntrinioClient(TEST_KEY, transport=httpx.MockTransport(handler)) as provider:
                with self.assertRaises(InvalidResponse):
                    provider.annual_growth(SECURITY, YEAR)


@override_settings(INTRINIO_API_KEY=TEST_KEY)
class AnnualGrowthPageTests(SimpleTestCase):
    def setUp(self):
        _request_budget.reset()
        self.addCleanup(_request_budget.reset)
        self.url = reverse("annual_growth", args=[SECURITY])
        self.query = {"fiscal_year": YEAR}

    def response(self, handler=growth_fixture_transport):
        with patch(
            "research.services.IntrinioClient",
            side_effect=lambda key: IntrinioClient(key, transport=httpx.MockTransport(handler)),
        ):
            return self.client.get(self.url, self.query)

    def test_initial_invalid_year_quarter_method_and_identifier_make_no_requests(self):
        with patch("research.services.IntrinioClient") as provider:
            self.assertContains(
                self.client.get(self.url), "No financial data has been requested yet"
            )
            for query in (
                {"fiscal_year": 1900},
                {"fiscal_year": "2019.5"},
                {"fiscal_year": datetime.now(UTC).year + 2},
                {"fiscal_year": YEAR, "fiscal_period": "Q1"},
                {"fiscal_period": "TTM"},
            ):
                self.assertNotContains(
                    self.client.get(self.url, query), "growth-panel", status_code=400
                )
            self.assertEqual(self.client.post(self.url, self.query).status_code, 405)
            self.assertEqual(self.client.head(self.url).status_code, 405)
            self.assertEqual(
                self.client.get(reverse("annual_growth", args=["bad.id"])).status_code, 404
            )
        provider.assert_not_called()

    def test_five_requests_render_growth_dollars_periods_and_versions(self):
        requests = []

        def handler(request):
            requests.append(request)
            return growth_fixture_transport(request)

        response = self.response(handler)
        for text in (
            "25.00%",
            "20.00%",
            "2018 FY → 2019 FY",
            "2017-10-01",
            "2019-09-30",
            "Dollar change",
            "positive prior value",
            "netincome",
            "totalrevenue",
            "not EPS growth",
            "not a point-in-time backtest",
        ):
            self.assertContains(response, text)
        self.assertEqual(len(requests), 5)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertNotContains(response, TEST_KEY)

    def test_negative_base_keeps_dollars_and_transition_but_not_percentage(self):
        with patch(
            "research.services.annual_growth",
            return_value=growth_bundle(prior_net="-100", current_net="50"),
        ):
            response = self.client.get(self.url, self.query)
        self.assertContains(response, "Loss to profit")
        self.assertContains(response, "the dollar change remains available")
        self.assertEqual(response.context["growth"].metrics[1].change, Decimal("150"))
        self.assertIsNone(response.context["growth"].metrics[1].percent)
        self.assertContains(response, "25.00%")

    def test_zero_base_and_zero_current_are_distinct(self):
        with patch(
            "research.services.annual_growth",
            return_value=growth_bundle(prior_revenue="0", current_net="0"),
        ):
            response = self.client.get(self.url, self.query)
        self.assertIsNone(response.context["growth"].metrics[0].percent)
        self.assertContains(response, "-100.00%")
        self.assertContains(response, "Profit to break-even")

    def test_duration_and_mixed_version_warnings_preserve_valid_comparison(self):
        bundle = growth_bundle()
        bundle = change_source(
            bundle,
            "current",
            fundamental=replace(bundle.current.fundamental, end_date=date(2019, 10, 7)),
        )
        bundle = change_source(
            bundle, "prior", fundamental=replace(bundle.prior.fundamental, type="restated")
        )
        with patch("research.services.annual_growth", return_value=bundle):
            response = self.client.get(self.url, self.query)
        self.assertContains(response, "Period lengths differ")
        self.assertContains(response, "Statement classifications differ")
        self.assertContains(response, "25.00%")
        self.assertEqual(response.context["growth"].current_days, 372)

    def test_gap_or_partial_response_never_shows_change_or_growth(self):
        bundle = growth_bundle()
        for altered in (
            change_source(bundle, "prior", pagination_complete=False),
            change_source(
                bundle,
                "current",
                fundamental=replace(bundle.current.fundamental, start_date=date(2018, 10, 2)),
            ),
        ):
            with patch("research.services.annual_growth", return_value=altered):
                response = self.client.get(self.url, self.query)
            self.assertTrue(
                all(
                    row.change is None and row.percent is None
                    for row in response.context["growth"].metrics
                )
            )
            self.assertContains(response, "Statement sources and versions")

    def test_missing_prior_resource_does_not_use_an_earlier_fy(self):
        requests = []

        def handler(request):
            requests.append(request)
            if "/lookup/income_statement/2018/" in request.url.path:
                return httpx.Response(404)
            return growth_fixture_transport(request)

        response = self.response(handler)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(len(requests), 4)
        self.assertNotIn("growth", response.context)
        self.assertNotContains(response, "growth-panel", status_code=404)

    def test_error_at_final_stage_clears_context_and_keeps_retry_after(self):
        for status, expected in ((403, 503), (429, 429)):
            _request_budget.reset()
            requests = []

            def handler(request, status=status, requests=requests):
                requests.append(request)
                return (
                    httpx.Response(status, headers={"Retry-After": "37"}, text=TEST_KEY)
                    if len(requests) == 5
                    else growth_fixture_transport(request)
                )

            response = self.response(handler)
            self.assertEqual(response.status_code, expected)
            self.assertEqual(len(requests), 5)
            self.assertNotIn("growth", response.context)
            self.assertNotIn("bundle", response.context)
            self.assertNotContains(response, TEST_KEY, status_code=expected)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            if status == 429:
                self.assertEqual(response.headers["Retry-After"], "37")

    def test_shared_client_budget_bounds_repeated_growth_loads(self):
        requests = []

        def handler(request):
            requests.append(request)
            return growth_fixture_transport(request)

        self.assertEqual(self.response(handler).status_code, 200)
        self.assertEqual(self.response(handler).status_code, 200)
        response = self.response(handler)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(len(requests), 10)
        self.assertNotContains(response, "growth-panel", status_code=429)

    @override_settings(INTRINIO_API_KEY="")
    def test_missing_key_does_not_construct_transport(self):
        with patch("research.services.IntrinioClient") as provider:
            response = self.client.get(self.url, self.query)
        self.assertContains(response, "Intrinio is not configured", status_code=503)
        provider.assert_not_called()

    def test_supplied_company_text_is_escaped(self):
        bundle = growth_bundle()
        bundle = change_source(
            bundle,
            "current",
            fundamental=replace(
                bundle.current.fundamental,
                company=replace(
                    bundle.current.fundamental.company, name="<script>fixture</script>"
                ),
            ),
        )
        with patch("research.services.annual_growth", return_value=bundle):
            response = self.client.get(self.url, self.query)
        self.assertContains(response, "&lt;script&gt;fixture&lt;/script&gt;")
        self.assertNotContains(response, "<script>fixture</script>")


class AnnualGrowthFormServiceTests(SimpleTestCase):
    def test_supported_years_and_explicit_fy_policy(self):
        self.assertFalse(AnnualGrowthForm().is_bound)
        for value in (1901, YEAR, datetime.now(UTC).year + 1):
            self.assertTrue(AnnualGrowthForm({"fiscal_year": value}).is_valid())
        for value in (1900, "2019.5", "", datetime.now(UTC).year + 2):
            self.assertFalse(AnnualGrowthForm({"fiscal_year": value}).is_valid())
        self.assertFalse(AnnualGrowthForm({"fiscal_year": YEAR, "fiscal_period": "Q1"}).is_valid())

    @override_settings(INTRINIO_API_KEY=TEST_KEY)
    def test_service_reserves_the_existing_budget_for_each_of_five_requests(self):
        reservations = []
        with (
            patch(
                "research.services.IntrinioClient",
                side_effect=lambda key: IntrinioClient(
                    key, transport=httpx.MockTransport(growth_fixture_transport)
                ),
            ),
            patch(
                "research.services._reserve_request",
                side_effect=lambda client: reservations.append(client),
            ),
        ):
            annual_growth(SECURITY, YEAR, "fixture-address")
        self.assertEqual(reservations, ["fixture-address"] * 5)
