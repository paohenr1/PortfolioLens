"""Independent multi-year values, missing-year boundaries and bounded transport."""

from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal, localcontext
from unittest.mock import patch

import httpx
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from market_data.contracts import AnnualStatementSeries, FinancialValue
from market_data.errors import InvalidResponse, ProviderError, ProviderRateLimited
from market_data.intrinio import IntrinioClient
from research.services import _request_budget, annual_statement_series
from research.trend_forms import StatementTrendForm
from research.trends import TREND_METRICS, calculate_statement_trends, trend_chart
from tests.test_fundamentals import SECURITY, YEAR, fixture_transport
from tests.test_intrinio import TEST_KEY
from tests.test_profitability import statement


def trend_bundle(code="income_statement", years=3):
    base = statement()
    security = replace(base.security, company_id=base.fundamental.company.id)
    sources = []
    for year in range(YEAR - years + 1, YEAR + 1):
        factor = year - 2016
        amounts = {
            "income_statement": (factor * 100, factor * 10, {0: -30, 1: -20, 2: 0, 3: 30}[factor]),
            "balance_sheet_statement": (factor * 100, factor * 40, factor * 60),
            "cash_flow_statement": (factor * 30, -factor * 5, 0),
        }[code]
        sources.append(
            replace(
                base,
                security=security,
                fundamental=replace(
                    base.fundamental,
                    id=f"fun_{year}",
                    fiscal_year=year,
                    statement_code=code,
                    start_date=None if code == "balance_sheet_statement" else date(year - 1, 10, 1),
                    end_date=date(year, 9, 30),
                ),
                values=tuple(
                    FinancialValue(tag, None, "usd", Decimal(amount), None)
                    for (_, tag), amount in zip(TREND_METRICS[code], amounts, strict=True)
                ),
            )
        )
    return AnnualStatementSeries(tuple(sources))


def alter_source(bundle, index=1, *, tag=None, period=None, **changes):
    source = bundle.statements[index]
    if period:
        source = replace(source, fundamental=replace(source.fundamental, **period))
    if tag is not None:
        source = replace(
            source,
            values=tuple(
                replace(row, **changes) if row.tag == tag else row for row in source.values
            ),
        )
    else:
        source = replace(source, **changes)
    sources = list(bundle.statements)
    sources[index] = source
    return replace(bundle, statements=tuple(sources))


def trend_fixture_transport(request):
    response = fixture_transport(request)
    if response.status_code != 200 or not request.url.path.endswith("/standardized_financials"):
        return response
    payload = response.json()
    code = payload["fundamental"]["statement_code"]
    year = payload["fundamental"]["fiscal_year"]
    bundle = trend_bundle(code, years=4)
    source = next(source for source in bundle.statements if source.fundamental.fiscal_year == year)
    payload["standardized_financials"] = [
        {
            "data_tag": {"tag": row.tag, "name": row.tag, "unit": row.unit, "sequence": index},
            "value": int(row.value),
        }
        for index, row in enumerate(source.values)
    ]
    return httpx.Response(200, json=payload)


class StatementTrendCalculationTests(SimpleTestCase):
    def result(self, bundle=None):
        return calculate_statement_trends(bundle or trend_bundle())

    def test_total_operating_income_tag_is_independent_of_fixture_configuration(self):
        bundle = trend_bundle(years=2)
        sources = tuple(
            replace(
                source,
                values=(
                    FinancialValue("totaloperatingincome", None, "usd", Decimal(amount), None),
                    FinancialValue("operatingincome", None, "usd", Decimal(999), None),
                ),
            )
            for source, amount in zip(bundle.statements, (20, 30), strict=True)
        )
        row = self.result(replace(bundle, statements=sources)).metrics[1]
        self.assertEqual(row.tag, "totaloperatingincome")
        self.assertEqual(tuple(v.value for v in row.values), (Decimal(20), Decimal(30)))
        self.assertEqual(row.changes[0].change, Decimal(10))
        self.assertEqual(row.changes[0].percent, Decimal("50.00"))
        aliases_only = tuple(replace(source, values=source.values[1:]) for source in sources)
        row = self.result(replace(bundle, statements=aliases_only)).metrics[1]
        self.assertTrue(all(value.value is None for value in row.values))
        self.assertIsNone(row.changes[0].change)

    def test_three_year_hand_calculated_values_and_adjacent_changes(self):
        result = self.result()
        row = result.metrics[0]
        self.assertEqual(tuple(v.year for v in row.values), (2017, 2018, 2019))
        self.assertEqual(
            tuple(v.value for v in row.values), (Decimal(100), Decimal(200), Decimal(300))
        )
        self.assertEqual(tuple(c.change for c in row.changes), (Decimal(100), Decimal(100)))
        self.assertEqual(
            tuple(c.percent for c in row.changes), (Decimal("100.00"), Decimal("50.00"))
        )

    def test_negative_and_zero_bases_retain_exact_changes_without_percent(self):
        row = self.result().metrics[2]
        self.assertEqual(
            tuple(v.value for v in row.values), (Decimal(-20), Decimal(0), Decimal(30))
        )
        self.assertEqual(tuple(c.change for c in row.changes), (Decimal(20), Decimal(30)))
        self.assertTrue(all(c.percent is None for c in row.changes))
        self.assertTrue(all("positive prior value" in c.issue for c in row.changes))

    def test_balance_sheet_observations_are_endpoint_changes_not_flow_sums(self):
        result = self.result(trend_bundle("balance_sheet_statement"))
        self.assertEqual(
            tuple(c.change for c in result.metrics[0].changes), (Decimal(100), Decimal(100))
        )
        self.assertEqual(result.metrics[0].values[-1].value, Decimal(300))
        self.assertIsNone(result.alignment_issue)

    def test_cash_flow_signs_and_zero_are_observations_not_missing_data(self):
        result = self.result(trend_bundle("cash_flow_statement"))
        self.assertEqual(
            tuple(v.value for v in result.metrics[1].values),
            (Decimal(-5), Decimal(-10), Decimal(-15)),
        )
        self.assertEqual(
            tuple(c.change for c in result.metrics[1].changes), (Decimal(-5), Decimal(-5))
        )
        self.assertTrue(all(c.percent is None for c in result.metrics[1].changes))
        self.assertEqual(tuple(v.value for v in result.metrics[2].values), (Decimal(0),) * 3)

    def test_one_missing_middle_tag_breaks_only_that_metrics_two_comparisons(self):
        bundle = trend_bundle()
        middle = bundle.statements[1]
        result = self.result(
            alter_source(bundle, values=tuple(v for v in middle.values if v.tag != "totalrevenue"))
        )
        self.assertIsNone(result.metrics[0].values[1].value)
        self.assertTrue(all(c.change is None for c in result.metrics[0].changes))
        self.assertTrue(all(c.change == Decimal(10) for c in result.metrics[1].changes))
        self.assertEqual(result.metrics[0].values[-1].value, Decimal(300))

    def test_null_and_missing_are_distinct_neither_is_zero(self):
        row = self.result(alter_source(trend_bundle(), tag="totalrevenue", value=None)).metrics[0]
        self.assertIn("Source value", row.values[1].issue)
        self.assertIsNone(row.values[1].value)

    def test_units_are_checked_per_cell_without_listing_currency_inference(self):
        for unit in (None, "USD", "eur", "usdpershare", "shares", "usd_millions"):
            result = self.result(alter_source(trend_bundle(), tag="totalrevenue", unit=unit))
            self.assertIn("unit of usd", result.metrics[0].values[1].issue)
            self.assertTrue(all(c.change is None for c in result.metrics[0].changes))
        bundle = trend_bundle()
        for index in range(3):
            bundle = alter_source(
                bundle, index, security=replace(bundle.statements[index].security, currency="EUR")
            )
        self.assertEqual(self.result(bundle).metrics[0].changes[0].percent, Decimal(100))

    def test_unsupported_numeric_types_nonfinite_and_bounds_withhold_cell(self):
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
                alter_source(trend_bundle(), tag="totalrevenue", value=value)
            ).metrics[0]
            self.assertIsNone(row.values[1].value)
            self.assertIn("finite financial number", row.values[1].issue)

    def test_exact_changes_and_rounding_ignore_ambient_decimal_context(self):
        bundle = alter_source(trend_bundle(), 0, tag="totalrevenue", value=Decimal("1e24"))
        bundle = alter_source(bundle, 1, tag="totalrevenue", value=Decimal("1e-18"))
        with localcontext() as context:
            context.prec, context.Emax, context.Emin = 2, 1, -1
            for signal in context.traps:
                context.traps[signal] = True
            row = self.result(bundle).metrics[0]
            chart = trend_chart(row)
        self.assertEqual(
            row.changes[0].change, Decimal("-999999999999999999999999.999999999999999999")
        )
        self.assertEqual(row.changes[0].percent, Decimal("-100.00"))
        self.assertEqual(chart["bars"][0]["height"], 120)

    def test_half_up_percentage_is_rounded_only_at_final_step(self):
        bundle = alter_source(trend_bundle(), 0, tag="totalrevenue", value=Decimal(100))
        for current, expected in (("101.005", "1.01"), ("98.995", "-1.01")):
            row = self.result(
                alter_source(bundle, 1, tag="totalrevenue", value=Decimal(current))
            ).metrics[0]
            self.assertEqual(row.changes[0].percent, Decimal(expected))

    def test_only_two_to_four_sources_are_supported(self):
        for years in (2, 4):
            self.assertEqual(len(self.result(trend_bundle(years=years)).metrics[0].values), years)
        bundle = trend_bundle()
        for sources in ((), bundle.statements[:1], bundle.statements * 2):
            result = self.result(replace(bundle, statements=sources))
            self.assertIn("Two to four", result.alignment_issue)
            self.assertEqual(result.metrics, ())

    def test_company_instrument_or_type_mismatch_withholds_entire_series(self):
        bundle = trend_bundle()
        for altered in (
            alter_source(bundle, security=replace(bundle.statements[1].security, id="sec_other")),
            alter_source(bundle, security=replace(bundle.statements[1].security, company_id=None)),
            alter_source(bundle, period={"statement_code": "cash_flow_statement"}),
            alter_source(
                bundle,
                period={
                    "company": replace(bundle.statements[1].fundamental.company, id="com_other")
                },
            ),
        ):
            self.assertIn("verified instrument", self.result(altered).alignment_issue)

    def test_duplicate_missing_out_of_order_years_quarters_are_not_reordered(self):
        bundle = trend_bundle()
        for altered in (
            replace(bundle, statements=tuple(reversed(bundle.statements))),
            alter_source(bundle, period={"fiscal_year": 2017}),
            alter_source(bundle, period={"fiscal_year": True}),
            alter_source(bundle, period={"fiscal_period": "Q4"}),
        ):
            self.assertIn("consecutive FY", self.result(altered).alignment_issue)

    def test_partial_duplicate_or_unknown_classification_breaks_year_without_bridge(self):
        bundle = trend_bundle()
        for altered in (
            alter_source(bundle, pagination_complete=False),
            alter_source(
                bundle, values=(*bundle.statements[1].values, bundle.statements[1].values[0])
            ),
            alter_source(bundle, period={"type": None}),
        ):
            result = self.result(altered)
            self.assertTrue(all(m.values[1].value is None for m in result.metrics))
            self.assertTrue(all(c.change is None for m in result.metrics for c in m.changes))
            self.assertEqual(result.metrics[0].values[-1].value, Decimal(300))

    def test_stub_or_missing_flow_dates_withhold_that_year(self):
        for changes in (
            {"start_date": None},
            {"end_date": None},
            {"start_date": date(2018, 4, 1)},
            {"start_date": date(2019, 1, 1)},
            {"start_date": datetime(2017, 10, 1)},
        ):
            result = self.result(alter_source(trend_bundle(), period=changes))
            self.assertIsNone(result.metrics[0].values[1].value)

    def test_gap_and_overlap_retain_values_but_disable_affected_pair(self):
        for start in (date(2017, 10, 2), date(2017, 9, 30)):
            result = self.result(alter_source(trend_bundle(), period={"start_date": start}))
            self.assertEqual(result.metrics[0].values[1].value, Decimal(200))
            self.assertIsNone(result.metrics[0].changes[0].change)
            self.assertIn("gap or overlap", result.metrics[0].changes[0].issue)
            self.assertIsNotNone(result.metrics[0].changes[1].change)

    def test_week_year_lengths_warn_and_do_not_annualize(self):
        bundle = trend_bundle()
        for index, start, end in (
            (0, date(2016, 9, 25), date(2017, 9, 23)),
            (1, date(2017, 9, 24), date(2018, 9, 29)),
            (2, date(2018, 9, 30), date(2019, 9, 28)),
        ):
            bundle = alter_source(bundle, index, period={"start_date": start, "end_date": end})
        row = self.result(bundle).metrics[0]
        self.assertEqual(row.changes[0].percent, Decimal(100))
        self.assertTrue(all("Period lengths differ" in c.warning for c in row.changes))

    def test_length_difference_above_seven_days_disables_pair(self):
        bundle = alter_source(trend_bundle(), 0, period={"start_date": date(2016, 9, 21)})
        bundle = alter_source(bundle, 1, period={"start_date": date(2017, 10, 1)})
        row = self.result(bundle).metrics[0]
        self.assertEqual(row.values[0].value, Decimal(100))
        self.assertIn("at most seven", row.changes[0].issue)

    def test_balance_endpoint_distance_requires_annual_ordered_dates(self):
        for end in (date(2017, 9, 30), date(2018, 3, 31), date(2019, 9, 30)):
            row = self.result(
                alter_source(trend_bundle("balance_sheet_statement"), period={"end_date": end})
            ).metrics[0]
            self.assertEqual(row.values[1].value, Decimal(200))
            self.assertIsNone(row.changes[0].change)
            self.assertIn("Balance-sheet dates", row.changes[0].issue)

    def test_mixed_classifications_warn_without_implying_shared_revision(self):
        row = self.result(alter_source(trend_bundle(), period={"type": "restated"})).metrics[0]
        self.assertEqual(row.changes[0].percent, Decimal(100))
        self.assertTrue(all("Classifications differ" in c.warning for c in row.changes))

    def test_bar_geometry_has_signed_baseline_exact_readouts_and_no_missing_point(self):
        result = self.result()
        chart = trend_chart(result.metrics[2])
        self.assertEqual(tuple(b["cy"] for b in chart["bars"]), (230, 150, 30))
        self.assertIn("-20 USD", chart["bars"][0]["label"])
        missing = self.result(alter_source(trend_bundle(), 0, tag="netincome", value=None)).metrics[
            2
        ]
        bars = trend_chart(missing)["bars"]
        self.assertFalse(bars[0]["available"])
        self.assertEqual(tuple(b["tabindex"] for b in bars), (-1, 0, -1))

    def test_all_zero_or_all_missing_chart_never_divides_by_zero_or_invents_bars(self):
        metric = self.result(trend_bundle("cash_flow_statement")).metrics[2]
        chart = trend_chart(metric)
        self.assertTrue(chart["available"])
        self.assertTrue(all(b["available"] and b["height"] == 0 for b in chart["bars"]))
        missing = replace(metric, values=tuple(replace(v, value=None) for v in metric.values))
        self.assertFalse(trend_chart(missing)["available"])


class StatementTrendAdapterTests(SimpleTestCase):
    def call(self, handler=trend_fixture_transport, years=3, **kwargs):
        with IntrinioClient(TEST_KEY, transport=httpx.MockTransport(handler)) as provider:
            return provider.annual_statement_series(
                SECURITY, "income_statement", YEAR, years, **kwargs
            )

    def test_five_seven_nine_requests_reserve_each_and_reuse_single_identity(self):
        for years in (2, 3, 4):
            requests, reservations = [], []

            def handler(request, requests=requests):
                requests.append(request)
                self.assertEqual(request.url.host, "api-v2.intrinio.com")
                return trend_fixture_transport(request)

            result = self.call(
                handler,
                years,
                before_request=lambda reservations=reservations: reservations.append(True),
            )
            self.assertEqual(len(requests), 1 + 2 * years)
            self.assertEqual(len(reservations), len(requests))
            self.assertEqual(sum(r.url.path == "/securities/" + SECURITY for r in requests), 1)
            self.assertEqual(
                tuple(s.fundamental.fiscal_year for s in result.statements),
                tuple(range(YEAR - years + 1, YEAR + 1)),
            )

    def test_invalid_full_range_count_or_type_is_rejected_before_io(self):
        with (
            patch("market_data.intrinio.IntrinioClient._request_json") as request,
            IntrinioClient(TEST_KEY) as provider,
        ):
            for security, code, end, years in (
                ("bad.id", "income_statement", YEAR, 3),
                (SECURITY, "unknown", YEAR, 3),
                (SECURITY, "income_statement", 1901, 4),
                (SECURITY, "income_statement", YEAR, True),
                (SECURITY, "income_statement", YEAR, 5),
            ):
                with self.assertRaises(ValueError):
                    provider.annual_statement_series(security, code, end, years)
            request.assert_not_called()

    def test_provider_failure_every_stage_stops_without_retry_or_period_substitution(self):
        for stage in range(1, 10):
            for status in (403, 404, 429):
                requests = []

                def handler(request, requests=requests, stage=stage, status=status):
                    requests.append(request)
                    return (
                        httpx.Response(status, text=TEST_KEY)
                        if len(requests) == stage
                        else trend_fixture_transport(request)
                    )

                with self.assertRaises(ProviderError):
                    self.call(handler, years=4)
                self.assertEqual(len(requests), stage)

    def test_quota_block_before_each_stage_does_not_send_denied_request(self):
        for stage in range(1, 10):
            requests, reservations = [], []

            def reserve(reservations=reservations, stage=stage):
                reservations.append(True)
                if len(reservations) == stage:
                    raise ProviderRateLimited(37)

            def handler(request, requests=requests):
                requests.append(request)
                return trend_fixture_transport(request)

            with self.assertRaises(ProviderRateLimited):
                self.call(handler, years=4, before_request=reserve)
            self.assertEqual(len(requests), stage - 1)

    def test_changed_lookup_values_period_company_or_date_is_rejected(self):
        for changes in ({"fiscal_year": 2019}, {"type": "restated"}, {"end_date": "2017-09-29"}):

            def handler(request, changes=changes):
                response = trend_fixture_transport(request)
                if request.url.path.endswith("/standardized_financials"):
                    payload = response.json()
                    payload["fundamental"].update(changes)
                    return httpx.Response(200, json=payload)
                return response

            with self.assertRaises(InvalidResponse):
                self.call(handler)


@override_settings(INTRINIO_API_KEY=TEST_KEY)
class StatementTrendPageTests(SimpleTestCase):
    def setUp(self):
        _request_budget.reset()
        self.addCleanup(_request_budget.reset)
        self.url = reverse("statement_trends", args=[SECURITY])
        self.query = {"statement": "income_statement", "end_year": YEAR, "years": 3}

    def response(self, handler=trend_fixture_transport, query=None):
        with patch(
            "research.services.IntrinioClient",
            side_effect=lambda key: IntrinioClient(key, transport=httpx.MockTransport(handler)),
        ):
            return self.client.get(self.url, self.query if query is None else query)

    def test_initial_invalid_range_quarter_method_id_do_not_construct_transport(self):
        with patch("research.services.IntrinioClient") as provider:
            self.assertContains(
                self.client.get(self.url), "No financial data has been requested yet"
            )
            for changes in (
                {"years": 5},
                {"end_year": 1901, "years": 4},
                {"end_year": "2019.5"},
                {"fiscal_period": "Q4"},
                {"statement": "unknown"},
            ):
                self.assertNotContains(
                    self.client.get(self.url, {**self.query, **changes}),
                    "trends-panel",
                    status_code=400,
                )
            self.assertEqual(self.client.post(self.url, self.query).status_code, 405)
            self.assertEqual(self.client.head(self.url).status_code, 405)
            self.assertEqual(
                self.client.get(reverse("statement_trends", args=["bad.id"])).status_code, 404
            )
        provider.assert_not_called()

    def test_three_year_render_has_charts_values_adjacent_changes_and_sources(self):
        response = self.response()
        for text in (
            "100.00%",
            "50.00%",
            "2017 FY",
            "2019 FY",
            "2018-09-30",
            "Classification",
            "currently retrieved",
            "positive prior",
            "point-in-time backtest",
            "SEC filing",
            "First calculable",
            "Retrieved",
            "Operating income",
            "netincome",
        ):
            self.assertContains(response, text)
        self.assertContains(response, 'class="chart-figure"', count=3)
        self.assertContains(response, 'class="metric-card"', count=3)
        self.assertContains(response, 'class="chart-point"', count=9)
        self.assertContains(response, 'src="/static/research/prices.js"')
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertNotContains(response, TEST_KEY)

    def test_balance_and_cash_flow_types_keep_correct_semantics_and_tags(self):
        for code, text in (
            ("balance_sheet_statement", "point-in-time observations"),
            ("cash_flow_statement", "netcashfromoperatingactivities"),
        ):
            _request_budget.reset()
            response = self.response(query={**self.query, "statement": code})
            self.assertContains(response, text)
            self.assertEqual(len(response.context["panels"]), 3)

    def test_partial_middle_source_breaks_comparisons_without_bridging_chart(self):
        def handler(request):
            response = trend_fixture_transport(request)
            if request.url.path.endswith("/standardized_financials"):
                payload = response.json()
                if payload["fundamental"]["fiscal_year"] == 2018:
                    payload["next_page"] = "fixture_cursor"
                return httpx.Response(200, json=payload)
            return response

        response = self.response(handler)
        self.assertContains(response, "Partial statement response")
        self.assertContains(response, 'class="chart-point"', count=6)
        self.assertTrue(
            all(c.change is None for m in response.context["trends"].metrics for c in m.changes)
        )

    def test_final_stage_failure_removes_all_loaded_context_and_preserves_retry_after(self):
        for status, expected in ((403, 503), (404, 404), (429, 429)):
            _request_budget.reset()
            requests = []

            def handler(request, requests=requests, status=status):
                requests.append(request)
                return (
                    httpx.Response(status, text=TEST_KEY, headers={"Retry-After": "37"})
                    if len(requests) == 7
                    else trend_fixture_transport(request)
                )

            response = self.response(handler)
            self.assertEqual(response.status_code, expected)
            self.assertNotIn("bundle", response.context)
            self.assertNotIn("trends", response.context)
            self.assertNotContains(response, "trends-panel", status_code=expected)
            self.assertNotContains(response, TEST_KEY, status_code=expected)
            if status == 429:
                self.assertEqual(response.headers["Retry-After"], "37")

    def test_missing_middle_resource_stops_without_earlier_year_fallback(self):
        requests = []

        def handler(request):
            requests.append(request)
            return (
                httpx.Response(404)
                if "/2018/FY" in request.url.path
                else trend_fixture_transport(request)
            )

        response = self.response(handler)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(len(requests), 4)
        self.assertNotContains(response, "trends-panel", status_code=404)

    def test_repeated_loads_share_existing_ten_request_budget(self):
        requests = []

        def handler(request):
            requests.append(request)
            return trend_fixture_transport(request)

        self.assertEqual(self.response(handler).status_code, 200)
        self.assertEqual(self.response(handler).status_code, 429)
        self.assertEqual(len(requests), 10)

    @override_settings(INTRINIO_API_KEY="")
    def test_missing_key_is_checked_before_transport_and_quota(self):
        with (
            patch("research.services.IntrinioClient") as provider,
            patch("research.services._reserve_request") as reserve,
        ):
            response = self.client.get(self.url, self.query)
        self.assertContains(response, "Intrinio is not configured", status_code=503)
        provider.assert_not_called()
        reserve.assert_not_called()

    def test_source_names_are_escaped_and_unexpected_exception_is_redacted(self):
        bundle = trend_bundle()
        sources = tuple(
            replace(
                s,
                fundamental=replace(
                    s.fundamental,
                    company=replace(s.fundamental.company, name="<script>fixture</script>"),
                ),
            )
            for s in bundle.statements
        )
        with patch(
            "research.services.annual_statement_series",
            return_value=replace(bundle, statements=sources),
        ):
            response = self.client.get(self.url, self.query)
        self.assertContains(response, "&lt;script&gt;fixture&lt;/script&gt;")
        self.assertNotContains(response, "<script>fixture</script>")
        with (
            patch("research.services.annual_statement_series", side_effect=RuntimeError(TEST_KEY)),
            self.assertLogs("research", level="ERROR") as logs,
        ):
            response = self.client.get(self.url, self.query)
        self.assertNotContains(response, TEST_KEY, status_code=503)
        self.assertNotIn(TEST_KEY, "".join(logs.output))


class StatementTrendFormServiceTests(SimpleTestCase):
    def test_full_annual_range_and_count_are_validated(self):
        query = {"statement": "income_statement", "end_year": YEAR, "years": 3}
        self.assertFalse(StatementTrendForm().is_bound)
        for years in (2, 3, 4):
            self.assertTrue(StatementTrendForm({**query, "years": years}).is_valid())
        for changes in (
            {"years": 1},
            {"years": 5},
            {"years": "3.5"},
            {"end_year": 1901, "years": 4},
            {"fiscal_period": "TTM"},
        ):
            self.assertFalse(StatementTrendForm({**query, **changes}).is_valid())

    @override_settings(INTRINIO_API_KEY=TEST_KEY)
    def test_service_reserves_existing_shared_budget_for_all_seven_stages(self):
        reservations = []
        with (
            patch(
                "research.services.IntrinioClient",
                side_effect=lambda key: IntrinioClient(
                    key, transport=httpx.MockTransport(trend_fixture_transport)
                ),
            ),
            patch(
                "research.services._reserve_request",
                side_effect=lambda client: reservations.append(client),
            ),
        ):
            annual_statement_series(SECURITY, "income_statement", YEAR, 3, "fixture-address")
        self.assertEqual(reservations, ["fixture-address"] * 7)
