"""Independent margin examples and bounded statement-page integration."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal, localcontext
from unittest.mock import patch

import httpx
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from market_data.contracts import Company, FinancialStatement, FinancialValue, Fundamental, Security
from market_data.intrinio import IntrinioClient
from research.profitability import profit_margins
from research.services import _request_budget
from tests.test_fundamentals import SECURITY, YEAR, fixture_transport
from tests.test_intrinio import TEST_KEY


def statement(*, revenue="200", gross="80", operating="30", net="-5", **overrides):
    values = tuple(
        FinancialValue(tag, None, "usd", Decimal(value), None)
        for tag, value in (
            ("totalrevenue", revenue),
            ("totalgrossprofit", gross),
            ("totaloperatingincome", operating),
            ("netincome", net),
        )
    )
    return FinancialStatement(
        Security(SECURITY, "FIX", "Fixture", "XNYS", "USD"),
        Fundamental(
            "fun_fixture",
            Company("com_fixture", "Fixture", "FIX"),
            "income_statement",
            2019,
            "FY",
            "reported",
            date(2018, 10, 1),
            date(2019, 9, 30),
            None,
            None,
            None,
        ),
        overrides.get("values", values),
        datetime(2020, 1, 1, tzinfo=UTC),
        overrides.get("pagination_complete", True),
    )


class ProfitMarginTests(SimpleTestCase):
    def percentages(self, result):
        return tuple(row.percent for row in profit_margins(result))

    def unavailable(self, result, text):
        for row in profit_margins(result):
            self.assertIsNone(row.percent)
            self.assertIn(text, row.issue)

    def test_hand_calculated_positive_and_loss_margins(self):
        self.assertEqual(
            self.percentages(statement()), (Decimal("40.00"), Decimal("15.00"), Decimal("-2.50"))
        )

    def test_provider_total_tags_are_used_without_alias_fallback(self):
        source = statement()
        # Independently spelled provider tags prevent synthetic fixtures from
        # masking a wrong source identifier again. Similar names are not aliases.
        correct = (
            FinancialValue("totalrevenue", None, "usd", Decimal(200), None),
            FinancialValue("totalgrossprofit", None, "usd", Decimal(80), None),
            FinancialValue("totaloperatingincome", None, "usd", Decimal(30), None),
            FinancialValue("netincome", None, "usd", Decimal(-5), None),
        )
        aliases = (
            FinancialValue("grossprofit", None, "usd", Decimal(999), None),
            FinancialValue("operatingincome", None, "usd", Decimal(999), None),
        )
        self.assertEqual(
            self.percentages(replace(source, values=correct + aliases)),
            (Decimal("40.00"), Decimal("15.00"), Decimal("-2.50")),
        )
        self.assertEqual(
            self.percentages(replace(source, values=(correct[0], correct[3], *aliases))),
            (None, None, Decimal("-2.50")),
        )

    def test_supplied_zero_profit_is_zero(self):
        self.assertEqual(
            self.percentages(statement(gross="0", operating="0", net="0")), (Decimal("0.00"),) * 3
        )

    def test_two_place_half_up_rounding_both_signs(self):
        self.assertEqual(
            self.percentages(
                statement(revenue="100", gross="1.005", operating="-1.005", net="1.0049")
            ),
            (Decimal("1.01"), Decimal("-1.01"), Decimal("1.00")),
        )

    def test_repeating_decimals_round_only_final_percentage(self):
        self.assertEqual(
            self.percentages(statement(revenue="3", gross="1", operating="-1", net="2")),
            (Decimal("33.33"), Decimal("-33.33"), Decimal("66.67")),
        )

    def test_tiny_negative_does_not_display_negative_zero(self):
        self.assertEqual(str(self.percentages(statement(net="-0.00001"))[2]), "0.00")

    def test_no_clamping_of_losses_or_margins_above_one_hundred(self):
        self.assertEqual(
            self.percentages(statement(revenue="100", gross="150", operating="-200", net="-500")),
            (Decimal("150.00"), Decimal("-200.00"), Decimal("-500.00")),
        )

    def test_zero_and_negative_revenue_are_undefined(self):
        for value in ("0", "-100"):
            self.unavailable(statement(revenue=value), "Revenue must be positive")

    def test_missing_and_null_revenue_are_distinct(self):
        source = statement()
        self.unavailable(
            replace(source, values=source.values[1:]), "tag totalrevenue was not supplied"
        )
        self.unavailable(
            replace(source, values=(replace(source.values[0], value=None), *source.values[1:])),
            "value totalrevenue was not supplied",
        )

    def test_missing_and_null_profit_leave_other_margins_available(self):
        source = statement()
        result = profit_margins(
            replace(
                source, values=tuple(row for row in source.values if row.tag != "totalgrossprofit")
            )
        )
        self.assertIn("tag totalgrossprofit", result[0].issue)
        self.assertEqual(result[2].percent, Decimal("-2.50"))
        result = profit_margins(
            replace(
                source,
                values=tuple(
                    replace(row, value=None) if row.tag == "netincome" else row
                    for row in source.values
                ),
            )
        )
        self.assertIn("value netincome", result[2].issue)
        self.assertEqual(result[0].percent, Decimal("40.00"))

    def test_explicit_usd_units_required_for_revenue(self):
        source = statement()
        for unit in (None, "eur", "usdpershare", "shares", "percentage", "USD", "usd_millions"):
            self.unavailable(
                replace(source, values=(replace(source.values[0], unit=unit), *source.values[1:])),
                "explicit provider unit of usd",
            )

    def test_bad_profit_unit_only_withholds_that_margin(self):
        source = statement()
        result = profit_margins(
            replace(
                source,
                values=tuple(
                    replace(row, unit="eur") if row.tag == "totalgrossprofit" else row
                    for row in source.values
                ),
            )
        )
        self.assertIsNone(result[0].percent)
        self.assertEqual(result[1].percent, Decimal("15.00"))

    def test_listing_currency_does_not_determine_statement_units(self):
        source = statement()
        self.assertEqual(
            self.percentages(replace(source, security=replace(source.security, currency="EUR"))),
            self.percentages(source),
        )

    def test_missing_reversed_or_same_day_dates_are_unavailable(self):
        source = statement()
        for start, end in (
            (None, source.fundamental.end_date),
            (source.fundamental.start_date, None),
            (date(2019, 9, 30), date(2019, 9, 30)),
            (date(2020, 1, 1), date(2019, 9, 30)),
            (datetime(2018, 10, 1), date(2019, 9, 30)),
        ):
            self.unavailable(
                replace(
                    source, fundamental=replace(source.fundamental, start_date=start, end_date=end)
                ),
                "valid start and end dates",
            )

    def test_all_quarters_preserve_period_margin_without_annualization(self):
        source = statement()
        for period in ("FY", "Q1", "Q2", "Q3", "Q4"):
            self.assertEqual(
                self.percentages(
                    replace(source, fundamental=replace(source.fundamental, fiscal_period=period))
                ),
                self.percentages(source),
            )

    def test_unsupported_period_is_not_a_trailing_estimate(self):
        source = statement()
        self.unavailable(
            replace(source, fundamental=replace(source.fundamental, fiscal_period="TTM")),
            "supported fiscal period",
        )

    def test_balance_sheet_and_cash_flow_do_not_imply_profitability(self):
        source = statement()
        for code in ("balance_sheet_statement", "cash_flow_statement"):
            self.assertEqual(
                profit_margins(
                    replace(source, fundamental=replace(source.fundamental, statement_code=code))
                ),
                (),
            )

    def test_partial_and_duplicate_tag_responses_are_unavailable(self):
        self.unavailable(statement(pagination_complete=False), "partial statement")
        source = statement()
        self.unavailable(
            replace(source, values=(*source.values, source.values[0])), "Duplicate source tags"
        )

    def test_restated_and_calculated_classifications_keep_current_values(self):
        source = statement()
        for kind in ("restated", "calculated", None):
            self.assertEqual(
                self.percentages(
                    replace(source, fundamental=replace(source.fundamental, type=kind))
                ),
                self.percentages(source),
            )

    def test_invalid_numbers_cannot_make_a_ratio(self):
        source = statement()
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
            Decimal("1.12345678901234567890123456789012345678901"),
        ):
            with self.subTest(value=repr(value)):
                self.unavailable(
                    replace(
                        source, values=(replace(source.values[0], value=value), *source.values[1:])
                    ),
                    "finite financial number",
                )

    def test_exact_rounding_is_independent_of_decimal_precision_and_traps(self):
        with localcontext() as context:
            context.prec = 2
            context.Emax = 1
            context.Emin = -1
            for signal in context.traps:
                context.traps[signal] = True
            self.assertEqual(
                self.percentages(statement(revenue="3", gross="1", operating="-1", net="2")),
                (Decimal("33.33"), Decimal("-33.33"), Decimal("66.67")),
            )

    def test_extreme_valid_financial_bounds_remain_exact(self):
        result = self.percentages(
            statement(revenue="1e-18", gross="1e24", operating="-1e24", net="0")
        )
        self.assertEqual(result, (Decimal("1e44"), Decimal("-1e44"), Decimal("0")))


@override_settings(INTRINIO_API_KEY=TEST_KEY)
class ProfitabilityPageTests(SimpleTestCase):
    def setUp(self):
        _request_budget.reset()
        self.addCleanup(_request_budget.reset)
        self.url = reverse("financials", args=[SECURITY])
        self.query = {
            "statement_code": "income_statement",
            "fiscal_year": YEAR,
            "fiscal_period": "FY",
        }

    def response(self, change=None, query=None):
        self.requests = []

        def handler(request):
            self.requests.append(request)
            response = fixture_transport(request)
            if change and request.url.path.endswith("/standardized_financials"):
                payload = response.json()
                change(payload)
                return httpx.Response(200, json=payload)
            return response

        with patch(
            "research.services.IntrinioClient",
            side_effect=lambda key: IntrinioClient(key, transport=httpx.MockTransport(handler)),
        ):
            return self.client.get(self.url, query or self.query)

    def test_existing_statement_three_requests_render_loss_and_missing_tags(self):
        response = self.response()
        self.assertEqual(len(self.requests), 3)
        self.assertContains(response, "Selected-period profitability")
        self.assertContains(response, "-0.02%")
        self.assertContains(response, "Source tag totalgrossprofit was not supplied")
        self.assertContains(response, "Source tag totaloperatingincome was not supplied")
        self.assertContains(response, "not a historical as-of snapshot")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertNotContains(response, TEST_KEY)

    def test_three_positive_margins_and_unchanged_raw_values(self):
        def values(payload):
            payload["standardized_financials"] = [
                {"data_tag": {"tag": tag, "unit": "usd", "name": tag}, "value": value}
                for tag, value in (
                    ("totalrevenue", 200),
                    ("totalgrossprofit", 80),
                    ("totaloperatingincome", 30),
                    ("netincome", 10),
                )
            ]

        response = self.response(values)
        for text in (
            "40.00%",
            "15.00%",
            "5.00%",
            "USD",
            "Source tags: totalgrossprofit / totalrevenue",
        ):
            self.assertContains(response, text)
        self.assertEqual(response.context["metrics"][0].value, "200")
        self.assertEqual(len(self.requests), 3)

    def test_initial_invalid_form_and_other_statements_have_no_margin_panel(self):
        with patch("research.services.IntrinioClient") as provider:
            self.assertNotContains(self.client.get(self.url), "Selected-period profitability")
            self.assertNotContains(
                self.client.get(self.url, {**self.query, "fiscal_period": "TTM"}),
                "Selected-period profitability",
                status_code=400,
            )
        provider.assert_not_called()
        for code in ("balance_sheet_statement", "cash_flow_statement"):
            _request_budget.reset()
            self.assertNotContains(
                self.response(query={**self.query, "statement_code": code}),
                "Selected-period profitability",
            )

    def test_partial_response_withholds_all_margins_but_keeps_values(self):
        response = self.response(lambda payload: payload.update(next_page="fixture_cursor"))
        self.assertContains(response, "partial statement response")
        self.assertContains(response, "1,234,567,890.125")
        self.assertTrue(all(row.percent is None for row in response.context["profit_margins"]))

    def test_missing_dates_withhold_margin_without_inferred_period(self):
        with patch(
            "research.services.company_statement",
            return_value=replace(
                statement(), fundamental=replace(statement().fundamental, start_date=None)
            ),
        ):
            response = self.client.get(self.url, self.query)
        self.assertContains(response, "valid start and end dates")
        self.assertContains(response, "Period start</dt><dd>Unavailable")

    def test_zero_denominator_and_wrong_units_do_not_display_ratios(self):
        for field, value, text in (
            ("value", 0, "Revenue must be positive"),
            ("unit", "usdpershare", "explicit provider unit of usd"),
        ):
            _request_budget.reset()

            def change(payload, field=field, value=value):
                row = next(
                    row
                    for row in payload["standardized_financials"]
                    if row["data_tag"]["tag"] == "totalrevenue"
                )
                (row if field == "value" else row["data_tag"])[field] = value

            response = self.response(change)
            self.assertContains(response, text)
            self.assertTrue(all(row.percent is None for row in response.context["profit_margins"]))

    def test_provider_failures_never_leave_margin_context(self):
        for status, expected in ((403, 503), (429, 429), (404, 404)):
            _request_budget.reset()
            with patch(
                "research.services.IntrinioClient",
                side_effect=lambda key, status=status: IntrinioClient(
                    key,
                    transport=httpx.MockTransport(
                        lambda request: httpx.Response(
                            status, headers={"Retry-After": "60"}, text=TEST_KEY
                        )
                    ),
                ),
            ):
                response = self.client.get(self.url, self.query)
            self.assertEqual(response.status_code, expected)
            self.assertNotIn("profit_margins", response.context)
            self.assertNotContains(response, "Selected-period profitability", status_code=expected)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertNotContains(response, TEST_KEY, status_code=expected)
            if status == 429:
                self.assertEqual(response.headers["Retry-After"], "60")

    def test_quarterly_period_is_visible_without_annualizing(self):
        response = self.response(query={**self.query, "fiscal_period": "Q2"})
        self.assertContains(response, "2019 Q2 · 2019-01-01 through 2019-03-31")
        self.assertContains(response, "no annualization")
        self.assertContains(response, "-0.02%")
