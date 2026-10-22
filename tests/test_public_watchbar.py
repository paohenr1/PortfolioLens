"""Public-source contracts, units, exact cross-rates, isolation and quota behavior."""

from datetime import UTC, date, datetime
from unittest.mock import Mock, patch

import httpx
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from market_data.errors import ProviderRateLimited
from market_data.public_markets import (
    ATOM,
    DATA,
    FX_URL,
    METADATA,
    TREASURY_URL,
    PublicFeedInvalid,
    PublicFeedUnavailable,
    PublicMarketClient,
    normalize_bitcoin,
    normalize_fx,
    normalize_treasury,
)
from research.services import _request_budget
from research.watchbar import bitcoin_item, daily_items, load_watchbar

TODAY = date(2026, 10, 22)


def treasury_xml(rows=None):
    rows = (
        rows
        if rows is not None
        else [("2026-10-20", "4.00", "4.20"), ("2026-10-21", "4.03", "4.18")]
    )
    entries = []
    for observed, two, ten in rows:
        values = "".join(
            f'<d:{name} m:null="true"/>' if value is None else f"<d:{name}>{value}</d:{name}>"
            for name, value in (("BC_2YEAR", two), ("BC_10YEAR", ten))
        )
        entries.append(
            f"<entry><content><m:properties><d:NEW_DATE>{observed}T00:00:00"
            f"</d:NEW_DATE>{values}</m:properties></content></entry>"
        )
    return (
        f'<feed xmlns="{ATOM[1:-1]}" xmlns:d="{DATA[1:-1]}" '
        f'xmlns:m="{METADATA[1:-1]}">{"".join(entries)}</feed>'
    ).encode()


def fx_payload():
    return {
        "seriesDetail": {"FXUSDCAD": {"label": "USD/CAD"}, "FXEURCAD": {"label": "EUR/CAD"}},
        "observations": [
            {"d": "2026-10-21", "FXUSDCAD": {"v": "1.25"}, "FXEURCAD": {"v": "1.5625"}},
            {"d": "2026-10-20", "FXUSDCAD": {"v": "1.20"}, "FXEURCAD": {"v": "1.44"}},
        ],
    }


class PublicContractTests(SimpleTestCase):
    def test_yields_keep_percent_units_and_change_uses_basis_points(self):
        data = normalize_treasury(treasury_xml(), today=TODAY, year=2026)
        items = {row["key"]: row for row in daily_items(data, "treasury")}
        self.assertEqual(items["2y"]["value"], "4.03%")
        self.assertEqual(items["2y"]["change"], "+3.0 bps")
        self.assertEqual(items["10y"]["change"], "-2.0 bps")
        self.assertEqual(items["10y"]["as_of"], date(2026, 10, 21))

    def test_zero_yield_is_valid_and_latest_missing_is_not_backfilled(self):
        data = normalize_treasury(
            treasury_xml([("2026-10-20", "1", "3"), ("2026-10-21", "0", None)]),
            today=TODAY,
            year=2026,
        )
        items = {row["key"]: row for row in daily_items(data, "treasury")}
        self.assertEqual(items["2y"]["value"], "0.00%")
        self.assertNotIn("available", items["10y"])

    def test_invalid_xml_identity_dates_numbers_and_entities_are_rejected(self):
        cases = [
            b"<html/>",
            b'<!DOCTYPE feed [<!ENTITY x "hello">]><feed/>',
            treasury_xml([("2026-10-23", "1", "2")]),
            treasury_xml([("2025-10-21", "1", "2")]),
            treasury_xml([("2026-10-21", "NaN", "2")]),
            treasury_xml([("2026-10-21", "1", "2")] * 2),
        ]
        for raw in cases:
            with self.subTest(raw=raw[:30]), self.assertRaises(PublicFeedInvalid):
                normalize_treasury(raw, today=TODAY, year=2026)

    def test_fx_normalizes_descending_dates_and_derives_the_correct_quote_direction(self):
        items = {
            row["key"]: row for row in daily_items(normalize_fx(fx_payload(), today=TODAY), "forex")
        }
        self.assertEqual(items["cad"]["value"], "1.2500")
        self.assertEqual(items["eur"]["value"], "1.2500")  # CAD/EUR divided by CAD/USD.
        self.assertEqual(items["eur"]["change"], "+4.17%")
        self.assertEqual(items["cad"]["change"], "+4.17%")
        self.assertEqual(items["eur"]["previous_date"], date(2026, 10, 20))
        self.assertIn("Derived daily reference", items["eur"]["note"])

    def test_missing_cross_rate_component_does_not_use_another_dates_value(self):
        payload = fx_payload()
        del payload["observations"][0]["FXEURCAD"]
        items = {
            row["key"]: row for row in daily_items(normalize_fx(payload, today=TODAY), "forex")
        }
        self.assertTrue(items["cad"]["available"])
        self.assertNotIn("available", items["eur"])

    def test_bad_fx_identity_duplicate_dates_and_zero_denominator_fail_closed(self):
        cases = []
        payload = fx_payload()
        payload["seriesDetail"]["FXUSDCAD"]["label"] = "CAD/USD"
        cases.append(payload)
        payload = fx_payload()
        payload["observations"] *= 2
        cases.append(payload)
        payload = fx_payload()
        payload["observations"][0]["FXUSDCAD"]["v"] = "0"
        cases.append(payload)
        for payload in cases:
            with self.assertRaises(PublicFeedInvalid):
                normalize_fx(payload, today=TODAY)

    def test_bitcoin_uses_one_venues_statistics_without_inventing_quote_time(self):
        data = normalize_bitcoin({"open": "100", "last": "110"})
        item = bitcoin_item(data)
        self.assertEqual(item["value"], "$110.00")
        self.assertEqual(item["change"], "+10.00%")
        self.assertEqual(item["source"], "Coinbase Exchange")
        self.assertNotIn("as_of", item)
        self.assertIn("Quote timestamp is not supplied", item["note"])
        for value in ("0", "NaN", True, None):
            with self.assertRaises(PublicFeedInvalid):
                normalize_bitcoin({"open": value, "last": "100"})

    def test_public_transport_admits_each_request_and_sends_no_credentials(self):
        calls = []

        def transport(request):
            calls.append(request)
            self.assertNotIn("api_key", request.url.params)
            self.assertNotIn("authorization", request.headers)
            if str(request.url).startswith(TREASURY_URL):
                today = datetime.now(UTC).date()
                return httpx.Response(200, content=treasury_xml([(today.isoformat(), "4", "5")]))
            if str(request.url).startswith(FX_URL):
                return httpx.Response(200, json=fx_payload())
            return httpx.Response(200, json={"open": "100", "last": "101"})

        reserve = Mock()
        with PublicMarketClient(
            before_request=reserve, transport=httpx.MockTransport(transport)
        ) as client:
            client.treasury()
            client.forex()
            client.bitcoin()
        self.assertEqual(len(calls), 3)
        self.assertEqual(reserve.call_count, 3)
        self.assertEqual(
            {request.url.host for request in calls},
            {"home.treasury.gov", "www.bankofcanada.ca", "api.exchange.coinbase.com"},
        )

    def test_redirect_duplicate_json_oversize_and_rate_limit_are_not_retried(self):
        for response, expected in (
            (
                httpx.Response(302, headers={"Location": "https://example.com"}),
                PublicFeedUnavailable,
            ),
            (httpx.Response(200, content=b'{"open":"1","last":"2","last":"3"}'), PublicFeedInvalid),
            (httpx.Response(429, headers={"Retry-After": "19"}), ProviderRateLimited),
        ):
            requests = []

            def transport(request, requests=requests, response=response):
                requests.append(request)
                return response

            with PublicMarketClient(
                before_request=lambda: None, transport=httpx.MockTransport(transport)
            ) as client:
                with self.assertRaises(expected):
                    client.bitcoin()
            self.assertEqual(len(requests), 1)
        with patch("market_data.public_markets.MAX_PUBLIC_BYTES", 20):
            with PublicMarketClient(
                before_request=lambda: None,
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(200, content=b"x" * 21)
                ),
            ) as client:
                with self.assertRaises(PublicFeedUnavailable):
                    client.bitcoin()


@override_settings(RATE_LIMIT_BACKEND="memory", PRIVATE_SITE=False)
class WatchbarIntegrationTests(SimpleTestCase):
    def setUp(self):
        _request_budget.reset()
        self.addCleanup(_request_budget.reset)

    def test_rate_limit_stops_all_remaining_sources_before_network(self):
        with patch("research.watchbar.PublicMarketClient") as factory:
            client = factory.return_value.__enter__.return_value
            client.treasury.side_effect = ProviderRateLimited(23)
            result = load_watchbar("fixture")
        self.assertEqual(result.rate_limit.retry_after, 23)
        client.forex.assert_not_called()
        client.bitcoin.assert_not_called()

    def test_existing_rate_limit_skips_all_source_requests(self):
        with patch("research.watchbar.PublicMarketClient") as factory:
            client = factory.return_value.__enter__.return_value
            result = load_watchbar("fixture", stop_error=ProviderRateLimited(11))
        client.treasury.assert_not_called()
        client.forex.assert_not_called()
        client.bitcoin.assert_not_called()
        self.assertEqual(result.rate_limit.retry_after, 11)

    def test_one_failed_source_preserves_other_available_sources(self):
        with patch("research.watchbar.PublicMarketClient") as factory:
            client = factory.return_value.__enter__.return_value
            client.treasury.side_effect = PublicFeedUnavailable()
            client.forex.return_value = normalize_fx(fx_payload(), today=TODAY)
            client.bitcoin.return_value = normalize_bitcoin({"open": "100", "last": "110"})
            result = load_watchbar("fixture")
        items = {row["key"]: row for row in result.items}
        self.assertNotIn("available", items["10y"])
        self.assertTrue(items["btc"]["available"])
        self.assertTrue(items["eur"]["available"])

    def test_public_only_overview_can_work_without_intrinio_credentials(self):
        from research.watchbar import WatchbarResult

        with override_settings(INTRINIO_API_KEY=""):
            with patch(
                "research.watchbar.load_watchbar",
                return_value=WatchbarResult(
                    [bitcoin_item(normalize_bitcoin({"open": "100", "last": "110"}))]
                ),
            ):
                response = self.client.post(reverse("load_market_indices"), {"period": "1M"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "$110.00")
        self.assertContains(response, "Coinbase Exchange")

    @override_settings(RATE_LIMIT_BACKEND="postgresql")
    def test_budget_storage_failure_blocks_public_network_io(self):
        from operations.rate_limits import BudgetUnavailable

        with patch("operations.rate_limits.reserve", side_effect=BudgetUnavailable):
            with patch("httpx.Client.stream", side_effect=AssertionError("Unexpected I/O")):
                result = load_watchbar("fixture")
        self.assertFalse(any(row.get("available") for row in result.items))
