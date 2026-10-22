"""Index identities, missing data, change arithmetic and bounded explicit requests."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import httpx
from django.test import Client, SimpleTestCase, override_settings
from django.urls import reverse

from market_data.errors import EntitlementDenied, InvalidResponse, ProviderRateLimited
from market_data.indices import (
    INDEX_CATALOG,
    IndexHistory,
    IndexObservation,
    normalize_index_history,
)
from market_data.intrinio import IntrinioClient
from research.market_views import index_presentation
from research.services import _request_budget

TEST_KEY = "index-test-key-never-render"


def payload(key="sp500", *, end=None):
    end = end or date(2026, 10, 21)
    symbol, identifier, _ = INDEX_CATALOG[key]
    return {
        "index": {"symbol": symbol, "id": identifier},
        "next_page": None,
        "historical_data": [
            {"date": (end - timedelta(days=1)).isoformat(), "value": 100},
            {"date": end.isoformat(), "value": Decimal("102.5")},
        ],
    }


class IndexContractTests(SimpleTestCase):
    def test_fixed_identity_and_one_bounded_page(self):
        calls = []

        def transport(request):
            calls.append(request)
            self.assertEqual(request.url.path, "/indices/stock_market/$SPX/historical_data/level")
            self.assertEqual(request.url.params["api_key"], TEST_KEY)
            self.assertEqual(request.url.params["page_size"], "400")
            return httpx.Response(
                200,
                content='{"index":{"symbol":"$SPX",'
                '"id":"ind_NX6GzO"},"historical_data":[{"date":"2026-10-21",'
                '"value":102.5}],"next_page":null}',
            )

        with IntrinioClient(TEST_KEY, transport=httpx.MockTransport(transport)) as provider:
            history = provider.index_history("sp500", date(2026, 10, 1), date(2026, 10, 21))
        self.assertEqual(len(calls), 1)
        self.assertEqual(history.observations[0].value, Decimal("102.5"))
        self.assertEqual(history.retrieved_at.tzinfo, UTC)

    def test_invalid_identity_pagination_dates_and_values_fail_closed(self):
        cases = []
        for field, value in (("id", "different-index"), ("symbol", "$NDX")):
            item = payload()
            item["index"][field] = value
            cases.append(item)
        item = payload()
        item["next_page"] = "remaining"
        cases.append(item)
        item = payload()
        del item["next_page"]
        cases.append(item)
        item = payload()
        item["historical_data"] *= 2
        cases.append(item)
        for value in (
            True,
            "102.5",
            Decimal("NaN"),
            Decimal("Infinity"),
            -1,
            0,
            Decimal("1e-100000"),
            Decimal("1e20"),
        ):
            item = payload()
            item["historical_data"][0]["value"] = value
            cases.append(item)
        for value in ("2026-10-22", "2026-09-30", "20261020", "2026-W43-3", None):
            item = payload()
            item["historical_data"][0]["date"] = value
            cases.append(item)
        for index, item in enumerate(cases):
            with self.subTest(case=index), self.assertRaises(InvalidResponse):
                normalize_index_history(item, "sp500", date(2026, 10, 1), date(2026, 10, 21))

    def test_missing_values_break_paths_and_do_not_invent_a_change(self):
        history = IndexHistory(
            "sp500",
            (
                IndexObservation(date(2026, 10, 19), Decimal(100)),
                IndexObservation(date(2026, 10, 20), None),
                IndexObservation(date(2026, 10, 21), Decimal(102)),
            ),
            datetime.now(UTC),
        )
        result = index_presentation(history, date(2026, 10, 19))
        self.assertNotIn("change", result)
        self.assertEqual(len(result["paths"]), 2)
        self.assertTrue(all("L" not in segment for segment in result["paths"]))

    def test_change_has_independent_arithmetic_and_actual_comparison_date(self):
        history = normalize_index_history(payload(), "sp500", date(2026, 10, 1), date(2026, 10, 21))
        result = index_presentation(history, date(2026, 10, 1))
        self.assertEqual(result["level"], "102.50")
        self.assertEqual(result["change"], "+2.50")
        self.assertEqual(result["percent"], "+2.50%")
        self.assertEqual(result["previous_date"], date(2026, 10, 20))

    def test_one_day_view_uses_latest_supplied_session_over_weekend(self):
        history = IndexHistory(
            "sp500",
            (
                IndexObservation(date(2026, 10, 15), Decimal(100)),
                IndexObservation(date(2026, 10, 16), Decimal(101)),
            ),
            datetime.now(UTC),
        )
        result = index_presentation(history, date(2026, 10, 17), single_session=True)
        self.assertTrue(result["available"])
        self.assertEqual(result["as_of"], date(2026, 10, 16))
        self.assertEqual(result["previous_date"], date(2026, 10, 15))
        self.assertTrue(result["paths"])

    def test_range_without_usable_observations_is_unavailable(self):
        item = payload()
        item["historical_data"] = []
        history = normalize_index_history(item, "sp500", date(2026, 10, 1), date(2026, 10, 21))
        self.assertNotIn("available", index_presentation(history, date(2026, 10, 1)))


@override_settings(INTRINIO_API_KEY=TEST_KEY, RATE_LIMIT_BACKEND="memory", PRIVATE_SITE=False)
class IndexHomepageTests(SimpleTestCase):
    def setUp(self):
        _request_budget.reset()
        self.addCleanup(_request_budget.reset)

    def history(self, key, start, end, client):
        return normalize_index_history(payload(key, end=end), key, start, end)

    def test_get_head_and_invalid_posts_make_no_market_requests(self):
        with patch("research.services.market_index_history") as provider:
            for method in (self.client.get, self.client.head):
                self.assertEqual(method(reverse("home")).status_code, 200)
            self.assertEqual(self.client.get(reverse("load_market_indices")).status_code, 405)
            for period in ("", "$SPX", "2Y"):
                self.assertEqual(
                    self.client.post(
                        reverse("load_market_indices"), {"period": period}
                    ).status_code,
                    400,
                )
        provider.assert_not_called()

    def test_three_fixed_indices_render_dates_without_credential_or_sample_data(self):
        with patch("research.services.market_index_history", side_effect=self.history) as provider:
            response = self.client.post(reverse("load_market_indices"), {"period": "1M"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(provider.call_count, 3)
        self.assertEqual([call.args[0] for call in provider.call_args_list], list(INDEX_CATALOG))
        self.assertContains(response, "102.50")
        self.assertContains(response, "+2.50%")
        self.assertContains(response, "Dates, values and sources")
        self.assertNotContains(response, TEST_KEY)
        self.assertNotContains(response, "markets-preview.js")
        self.assertNotContains(response, "5,842.47")
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertLess(provider.call_args.args[2], datetime.now(UTC).date())

    def test_one_denied_index_does_not_hide_other_valid_cards(self):
        def history(key, *args):
            if key == "dow":
                raise EntitlementDenied()
            return self.history(key, *args)

        with patch("research.services.market_index_history", side_effect=history):
            response = self.client.post(reverse("load_market_indices"), {"period": "1M"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "102.50", count=2)
        self.assertContains(response, EntitlementDenied.message)

    def test_rate_limit_stops_remaining_requests_and_preserves_retry_after(self):
        def provider(key, *args):
            if key == "dow":
                raise ProviderRateLimited(17)
            return self.history(key, *args)

        with patch("research.services.market_index_history", side_effect=provider) as load:
            response = self.client.post(reverse("load_market_indices"), {"period": "1M"})
        self.assertEqual(load.call_count, 2)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["Retry-After"], "17")
        self.assertContains(response, "102.50", status_code=429)

    @override_settings(INTRINIO_API_KEY="")
    def test_missing_key_never_constructs_provider(self):
        with patch("research.services.IntrinioClient") as provider:
            response = self.client.post(reverse("load_market_indices"), {"period": "1D"})
        self.assertEqual(response.status_code, 503)
        provider.assert_not_called()

    def test_csrf_is_required_before_any_provider_io(self):
        with patch("research.services.market_index_history") as provider:
            response = Client(enforce_csrf_checks=True).post(
                reverse("load_market_indices"), {"period": "1M"}
            )
        self.assertEqual(response.status_code, 403)
        provider.assert_not_called()

    def test_index_service_consumes_shared_budget(self):
        history = self.history("sp500", date(2026, 10, 1), date(2026, 10, 21), "test")
        with patch("research.services._reserve_request") as reserve:
            with patch("research.services.IntrinioClient") as factory:
                factory.return_value.__enter__.return_value.index_history.return_value = history
                from research.services import market_index_history

                result = market_index_history(
                    "sp500", date(2026, 10, 1), date(2026, 10, 21), "test"
                )
        self.assertEqual(result, history)
        reserve.assert_called_once_with("test")
