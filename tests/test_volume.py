"""Volume is optional share data, with independent basis and exact decimal display."""

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal, Inexact, Rounded, localcontext
from unittest.mock import patch

import httpx
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from market_data.errors import InvalidResponse
from market_data.intrinio import IntrinioClient
from market_data.prices import normalize_daily_price
from research.forms import PriceHistoryForm
from research.services import _request_budget, _reserve_request
from research.volume_charts import build_volume_chart
from tests.test_intrinio import TEST_KEY
from tests.test_prices import observation, payload
from tests.test_stock_risk import stock_history

D = Decimal
DAY = date(2020, 1, 2)


def volume_history():
    history = stock_history(("100", "110", "99", "105"))
    rows = tuple(
        replace(
            row,
            volume=D(raw) if raw is not None else None,
            adjusted_volume=D(adj) if adj is not None else None,
        )
        for row, raw, adj in zip(
            history.observations,
            ("1000", "0", None, "500"),
            ("500.125", "0", "900.5", None),
            strict=True,
        )
    )
    return replace(history, observations=rows)


class VolumeNormalizationTests(SimpleTestCase):
    def normalize(self, volume=None, adjusted=None):
        return normalize_daily_price(
            {**observation(DAY), "volume": volume, "adj_volume": adjusted}, DAY, DAY
        )

    def test_absent_and_null_fields_preserve_existing_price_only_contract(self):
        for data in (observation(DAY), {**observation(DAY), "volume": None, "adj_volume": None}):
            result = normalize_daily_price(data, DAY, DAY)
            self.assertIsNone(result.volume)
            self.assertIsNone(result.adjusted_volume)
            self.assertEqual(result.close, D(10))

    def test_integer_and_fractional_raw_and_adjusted_volume_are_exact(self):
        result = self.normalize(123456789, D("123456789.123456789012345678"))
        self.assertEqual(result.volume, D(123456789))
        self.assertEqual(result.adjusted_volume, D("123456789.123456789012345678"))
        self.assertEqual(self.normalize(D("0.125"), D("0.0625")).volume, D("0.125"))

    def test_zero_is_known_data_not_missing(self):
        result = self.normalize(0, D(0))
        self.assertEqual(result.volume, D(0))
        self.assertEqual(result.adjusted_volume, D(0))

    def test_non_numeric_nonfinite_and_negative_values_fail_both_fields(self):
        for value in (True, False, "100", 1.5, [], {}, D(-1), D("NaN"), D("sNaN"), D("Infinity")):
            for args in ((value, 100), (100, value)):
                with self.subTest(value=value, args=args), self.assertRaises(InvalidResponse):
                    self.normalize(*args)

    def test_numeric_representation_and_magnitude_bounds_are_enforced(self):
        for value in (
            D("1e19"),
            D("1e-19"),
            D("0e19"),
            D("100000000000000000.1234567890123456789"),
        ):
            with self.subTest(value=value), self.assertRaises(InvalidResponse):
                self.normalize(value)
        for value in (D("1e18"), D("1e-18"), D("100000000000000000.123456789012345678")):
            self.assertEqual(self.normalize(value).volume, value)

    def test_adapter_parses_json_fractional_numbers_without_float_round_trip(self):
        data = payload([{**observation(DAY), "volume": 10, "adj_volume": 1}])
        import json

        body = json.dumps(data).replace('"adj_volume": 1', '"adj_volume": 1.123456789012345678')
        client = IntrinioClient(
            TEST_KEY, transport=httpx.MockTransport(lambda r: httpx.Response(200, text=body))
        )
        result = client.price_history("sec_fixture_primary", DAY, DAY)
        self.assertEqual(result.observations[0].adjusted_volume, D("1.123456789012345678"))

    def test_bad_optional_volume_rejects_response_instead_of_silent_substitution(self):
        data = payload([{**observation(DAY), "volume": "not-volume"}])
        client = IntrinioClient(
            TEST_KEY, transport=httpx.MockTransport(lambda r: httpx.Response(200, json=data))
        )
        with self.assertRaises(InvalidResponse):
            client.price_history("sec_fixture_primary", DAY, DAY)


class VolumeChartTests(SimpleTestCase):
    def test_independent_basis_and_missing_values_do_not_fall_back(self):
        history = volume_history()
        raw, adjusted = [build_volume_chart(history, basis) for basis in ("raw", "adjusted")]
        self.assertEqual([p.value for p in raw.points], ["1000", "0", "500"])
        self.assertEqual([p.value for p in adjusted.points], ["500.125", "0", "900.5"])
        self.assertEqual(raw.latest.date, date(2020, 1, 7))
        self.assertEqual(adjusted.latest.date, date(2020, 1, 6))
        self.assertEqual(raw.missing_count, 1)
        self.assertEqual(adjusted.missing_count, 1)

    def test_values_use_zero_baseline_and_calendar_spacing(self):
        chart = build_volume_chart(volume_history(), "raw")
        self.assertEqual(chart.points[0].height, 250)
        self.assertEqual(chart.points[0].y, 35)
        self.assertEqual(chart.points[1].height, 0)
        self.assertEqual(chart.points[1].y, 285)
        self.assertEqual(chart.points[2].height, 125)
        self.assertEqual([p.x for p in chart.points], [95, 251, 875])

    def test_unknown_and_incomplete_periods_are_not_plotted_but_table_retains_values(self):
        history = volume_history()
        rows = (
            replace(history.observations[0], intraperiod=True),
            replace(history.observations[1], intraperiod=None),
            *history.observations[2:],
        )
        chart = build_volume_chart(replace(history, observations=rows), "raw")
        self.assertEqual(chart.unconfirmed_count, 2)
        self.assertEqual([p.value for p in chart.points], ["500"])
        self.assertEqual(chart.rows[-1].volume, "1000")
        self.assertEqual(chart.rows[-1].period_status, "Incomplete period")
        self.assertEqual(chart.rows[-2].period_status, "Period status unavailable")

    def test_zero_series_retains_selectable_points_and_one_share_scale(self):
        history = volume_history()
        rows = tuple(replace(row, volume=D(0)) for row in history.observations)
        chart = build_volume_chart(replace(history, observations=rows), "raw")
        self.assertEqual(len(chart.points), 4)
        self.assertEqual(chart.scale_label, "1")
        self.assertTrue(all(p.y == 285 and p.height == 0 for p in chart.points))
        self.assertEqual(chart.latest.value, "0")

    def test_no_values_is_empty_not_a_zero_series(self):
        history = stock_history()
        chart = build_volume_chart(history, "raw")
        self.assertEqual(chart.points, ())
        self.assertEqual(chart.missing_count, 3)
        self.assertIsNone(chart.latest)
        self.assertEqual(chart.rows[0].volume, "Unavailable")
        self.assertEqual(build_volume_chart(replace(history, observations=()), "raw").rows, ())

    def test_single_date_has_bounded_visible_bar_without_division_by_zero(self):
        history = stock_history(("100",))
        row = replace(history.observations[0], volume=D("0.125"))
        chart = build_volume_chart(replace(history, observations=(row,)), "raw")
        self.assertEqual(chart.points[0].height, 250)
        self.assertEqual(chart.points[0].value, "0.125")
        self.assertEqual(chart.bar_width, 18)

    def test_long_range_uses_bounded_bar_width_without_aggregation(self):
        history = volume_history()
        history = replace(history, end_date=history.start_date + timedelta(days=365))
        chart = build_volume_chart(history, "raw")
        self.assertEqual(chart.bar_width, 1)
        self.assertEqual(len(chart.points), 3)
        self.assertTrue(all(95 <= p.x <= 875 and 35 <= p.y <= 285 for p in chart.points))

    def test_geometry_and_exact_labels_ignore_ambient_decimal_traps(self):
        history = volume_history()
        expected = build_volume_chart(history, "adjusted")
        with localcontext() as context:
            context.prec, context.Emax, context.Emin = 2, 2, -2
            context.traps[Inexact] = context.traps[Rounded] = True
            self.assertEqual(build_volume_chart(history, "adjusted"), expected)

    def test_unsupported_basis_is_a_programming_error(self):
        with self.assertRaises(ValueError):
            build_volume_chart(volume_history(), "fallback")

    def test_partial_history_is_displayed_without_manufacturing_full_series(self):
        history = volume_history()
        self.assertEqual(
            build_volume_chart(history, "raw"),
            build_volume_chart(replace(history, pagination_complete=False), "raw"),
        )


@override_settings(INTRINIO_API_KEY=TEST_KEY)
class VolumePageTests(SimpleTestCase):
    def setUp(self):
        _request_budget.reset()
        self.addCleanup(_request_budget.reset)
        self.url = reverse("prices", args=["sec_fixture_primary"])
        self.query = {"start_date": "2020-01-02", "end_date": "2020-01-06", "basis": "adjusted"}

    def data(self):
        return payload(
            [
                {**observation(DAY, 100, 100), "volume": 1000, "adj_volume": 500.125},
                {**observation(date(2020, 1, 3), 110, 110), "volume": 0, "adj_volume": 0},
                {**observation(date(2020, 1, 6), 99, 99), "volume": 2000, "adj_volume": None},
            ]
        )

    def provider(self, handler):
        return patch(
            "research.services.IntrinioClient",
            side_effect=lambda key: IntrinioClient(key, transport=httpx.MockTransport(handler)),
        )

    def test_initial_invalid_and_volume_only_submission_make_no_provider_call(self):
        with patch("research.services.IntrinioClient") as provider:
            initial = self.client.get(self.url)
            for query in ({**self.query, "volume_basis": "auto"}, {"volume_basis": "raw"}):
                response = self.client.get(self.url, query)
                self.assertEqual(response.status_code, 400)
                self.assertNotContains(response, 'class="volume-panel"', status_code=400)
        provider.assert_not_called()
        self.assertContains(initial, "Volume basis")
        self.assertNotIn("volume_chart", initial.context)

    def test_old_query_defaults_to_raw_and_price_basis_is_independent(self):
        calls = []
        with self.provider(
            lambda r: calls.append(r.url.path) or httpx.Response(200, json=self.data())
        ):
            raw = self.client.get(self.url, self.query)
            adjusted = self.client.get(
                self.url, {**self.query, "basis": "raw", "volume_basis": "adjusted"}
            )
        self.assertEqual(calls, ["/securities/sec_fixture_primary/prices"] * 2)
        self.assertEqual(raw.context["volume_basis"], "raw")
        self.assertContains(raw, "Raw volume · Daily share volume")
        self.assertContains(adjusted, "Adjusted volume · Daily share volume")
        self.assertEqual(
            [p.value for p in adjusted.context["volume_chart"].points], ["500.125", "0"]
        )
        self.assertEqual(adjusted.context["basis"], "raw")
        self.assertContains(raw, 'class="price-chart"', count=3)
        self.assertContains(raw, "research/prices.js", count=1)
        self.assertContains(raw, "share count, not currency turnover")
        self.assertEqual(raw.headers["Cache-Control"], "no-store")
        self.assertNotContains(raw, TEST_KEY)

    def test_missing_volume_keeps_price_and_risk_without_zero_substitution(self):
        data = self.data()
        for row in data["stock_prices"]:
            row.pop("volume")
            row.pop("adj_volume")
        with self.provider(lambda r: httpx.Response(200, json=data)):
            response = self.client.get(self.url, self.query)
        self.assertContains(response, "No completed volume available")
        self.assertContains(response, 'class="price-chart"', count=2)
        self.assertContains(response, "3 returned observations lack the selected volume")
        self.assertEqual(response.context["stock_risk"].daily_volatility_percent, D("14.1421"))

    def test_volume_without_prices_includes_point_script_and_table(self):
        data = self.data()
        for row in data["stock_prices"]:
            row["close"] = row["adj_close"] = None
        with self.provider(lambda r: httpx.Response(200, json=data)):
            response = self.client.get(self.url, self.query)
        self.assertContains(response, "No completed closes available")
        self.assertContains(response, 'class="price-chart"', count=1)
        self.assertContains(response, "research/prices.js", count=1)
        self.assertEqual(len(response.context["volume_chart"].points), 3)

    def test_unconfirmed_values_stay_in_volume_table_without_bars(self):
        data = self.data()
        data["stock_prices"][2]["intraperiod"] = True
        with self.provider(lambda r: httpx.Response(200, json=data)):
            response = self.client.get(self.url, self.query)
        self.assertContains(response, "1 incomplete or unconfirmed volume period excluded")
        self.assertEqual(len(response.context["volume_chart"].points), 2)
        self.assertEqual(response.context["volume_chart"].rows[0].volume, "2000")

    def test_partial_paging_uses_existing_cap_and_labels_volume_as_partial(self):
        calls = []

        def handler(request):
            calls.append(request)
            row = {
                **observation(
                    (DAY, date(2020, 1, 3), date(2020, 1, 6), date(2020, 1, 7))[len(calls) - 1]
                ),
                "volume": 100,
            }
            return httpx.Response(200, json=payload([row], f"page-{len(calls)}"))

        with self.provider(handler):
            response = self.client.get(self.url, {**self.query, "end_date": "2020-01-08"})
        self.assertEqual(len(calls), 4)
        self.assertContains(response, "Partial volume history")
        self.assertEqual(len(response.context["volume_chart"].points), 4)
        self.assertIsNone(response.context["stock_drawdown_chart"])

    def test_malformed_volume_clears_all_price_risk_and_volume_context(self):
        data = self.data()
        data["stock_prices"][0]["adj_volume"] = "bad"
        with self.provider(lambda r: httpx.Response(200, json=data)):
            response = self.client.get(self.url, self.query)
        self.assertContains(response, 'data-error-code="invalid_response"', status_code=503)
        self.assertNotIn("history", response.context)
        self.assertNotIn("volume_chart", response.context)
        self.assertNotContains(response, 'class="price-chart"', status_code=503)

    def test_existing_quota_and_provider_errors_have_no_volume_context(self):
        for _ in range(10):
            _reserve_request("127.0.0.1")
        calls = []
        with self.provider(lambda r: calls.append(r) or httpx.Response(200, json=self.data())):
            limited = self.client.get(self.url, self.query)
        self.assertEqual(calls, [])
        self.assertEqual(limited.status_code, 429)
        self.assertNotIn("volume_chart", limited.context)
        for code, status in ((403, 503), (429, 429), (500, 503)):
            _request_budget.reset()
            with self.provider(
                lambda r, code=code: httpx.Response(
                    code, text=TEST_KEY, headers={"Retry-After": "60"}
                )
            ):
                response = self.client.get(self.url, self.query)
            self.assertNotIn("volume_chart", response.context)
            self.assertNotContains(response, TEST_KEY, status_code=status)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            if code == 429:
                self.assertEqual(response.headers["Retry-After"], "60")

    def test_unexpected_volume_error_discards_staged_context_and_redacts_logs(self):
        with patch("research.services.historical_prices", return_value=volume_history()):
            with patch("research.views.build_volume_chart", side_effect=RuntimeError(TEST_KEY)):
                with self.assertLogs("research", level="ERROR") as logs:
                    response = self.client.get(self.url, self.query)
        self.assertNotIn("history", response.context)
        self.assertNotIn(TEST_KEY, "\n".join(logs.output))
        self.assertNotContains(response, TEST_KEY, status_code=503)

    def test_form_default_and_explicit_volume_basis_are_validated_without_io(self):
        for data, expected in (
            (self.query, "raw"),
            ({**self.query, "volume_basis": "adjusted"}, "adjusted"),
        ):
            form = PriceHistoryForm(data)
            self.assertTrue(form.is_valid())
            self.assertEqual(form.cleaned_data["volume_basis"], expected)
        self.assertFalse(PriceHistoryForm({**self.query, "volume_basis": "auto"}).is_valid())
