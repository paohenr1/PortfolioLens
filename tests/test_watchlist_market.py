"""Independent daily examples, owner isolation, quota limits and saved defaults."""

import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from unittest import skipUnless
from unittest.mock import patch

import httpx
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import Client, SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from market_data.contracts import DailyPrice, PriceHistory, Security
from market_data.errors import (
    CredentialsMissing,
    EntitlementDenied,
    ProviderError,
    ProviderRateLimited,
)
from market_data.intrinio import IntrinioClient
from research.services import _request_budget, _reserve_request
from tests.test_intrinio import TEST_KEY
from watchlists import services
from watchlists.forms import WatchlistPreferencesForm
from watchlists.market import daily_observation
from watchlists.market_services import load_market_information
from watchlists.models import Watchlist, WatchlistItem

DAY = date(2020, 1, 2)
RETRIEVED = datetime(2020, 1, 3, tzinfo=UTC)


def daily_history(security_id="sec_watchlist_0", market_date=DAY, **changes):
    result = PriceHistory(
        Security(security_id, "TST", "Invented daily example", "XNYS", "USD"),
        (
            DailyPrice(
                market_date, Decimal("30"), Decimal("15"), False, Decimal("120"), Decimal("240.5")
            ),
        ),
        market_date,
        market_date,
        RETRIEVED,
        True,
    )
    return replace(result, **changes)


def daily_transport(request):
    identifier = request.url.path.split("/")[2]
    return httpx.Response(
        200,
        json={
            "security": {"id": identifier, "currency": "USD", "exchange_mic": "XNYS"},
            "stock_prices": [
                {
                    "date": request.url.params["start_date"],
                    "frequency": "daily",
                    "intraperiod": False,
                    "close": 30,
                    "adj_close": 15,
                    "volume": 120,
                    "adj_volume": 240.5,
                }
            ],
            "next_page": None,
        },
    )


class DailyObservationTests(SimpleTestCase):
    def result(self, history=None, price_basis="raw", volume_basis="raw"):
        return daily_observation(
            history or daily_history(), "sec_watchlist_0", DAY, price_basis, volume_basis
        )

    def test_raw_and_adjusted_price_volume_bases_are_independent_and_exact(self):
        for price_basis, volume_basis, close, volume in (
            ("raw", "raw", "30", "120"),
            ("adjusted", "raw", "15", "120"),
            ("raw", "adjusted", "30", "240.5"),
            ("adjusted", "adjusted", "15", "240.5"),
        ):
            result = self.result(price_basis=price_basis, volume_basis=volume_basis)
            self.assertEqual(result.close, Decimal(close))
            self.assertEqual(result.volume, Decimal(volume))
            self.assertIsNone(result.price_issue)
            self.assertIsNone(result.volume_issue)

    def test_missing_selected_price_never_falls_back_and_preserves_volume(self):
        base = daily_history()
        row = replace(base.observations[0], adjusted_close=None)
        result = self.result(replace(base, observations=(row,)), price_basis="adjusted")
        self.assertIsNone(result.close)
        self.assertIn("not supplied", result.price_issue)
        self.assertEqual(result.volume, Decimal("120"))

    def test_missing_adjusted_volume_never_substitutes_raw_volume(self):
        base = daily_history()
        row = replace(base.observations[0], adjusted_volume=None)
        result = self.result(replace(base, observations=(row,)), volume_basis="adjusted")
        self.assertIsNone(result.volume)
        self.assertEqual(result.close, Decimal("30"))

    def test_known_zero_and_fractional_values_are_not_missing(self):
        base = daily_history()
        row = replace(base.observations[0], close=Decimal("0"), volume=Decimal("0.125"))
        result = self.result(replace(base, observations=(row,)))
        self.assertEqual(result.close, 0)
        self.assertEqual(result.volume, Decimal("0.125"))
        row = replace(row, volume=Decimal("0"))
        self.assertEqual(self.result(replace(base, observations=(row,))).volume, 0)

    def test_unknown_or_intraperiod_observation_withholds_both_fields(self):
        base = daily_history()
        for flag in (None, True, 0):
            row = replace(base.observations[0], intraperiod=flag)
            result = self.result(replace(base, observations=(row,)))
            self.assertIsNone(result.close)
            self.assertIsNone(result.volume)
            self.assertIn("explicitly marked complete", result.price_issue)

    def test_partial_or_unknown_completion_withholds_even_supplied_values(self):
        for completion in (False, None, 1):
            result = self.result(daily_history(pagination_complete=completion))
            self.assertIsNone(result.close)
            self.assertIsNone(result.volume)
            self.assertIn("Incomplete", result.price_issue)

    def test_empty_duplicate_or_wrong_date_never_falls_back(self):
        base = daily_history()
        row = base.observations[0]
        for observations in (
            (),
            (row, row),
            (replace(row, date=DAY - timedelta(days=1)),),
            (replace(row, date=datetime(2020, 1, 2)),),
        ):
            result = self.result(replace(base, observations=observations))
            self.assertIsNone(result.close)
            self.assertIsNone(result.volume)

    def test_request_identity_dates_and_aware_retrieval_must_match(self):
        base = daily_history()
        for changes in (
            {"security": replace(base.security, id="sec_other")},
            {"start_date": DAY - timedelta(days=1)},
            {"end_date": DAY + timedelta(days=1)},
            {"retrieved_at": datetime(2020, 1, 3)},
            {"retrieved_at": datetime(2020, 1, 1, tzinfo=UTC)},
            {"retrieved_at": DAY},
        ):
            result = self.result(replace(base, **changes))
            self.assertIsNone(result.close)
            self.assertIsNone(result.volume)

    def test_non_usd_price_keeps_its_response_currency_without_conversion(self):
        base = daily_history()
        result = self.result(
            replace(base, security=replace(base.security, currency="CAD", exchange_mic="XTSE"))
        )
        self.assertEqual(result.close, Decimal("30"))

    def test_missing_or_malformed_reference_unit_withholds_price_only(self):
        base = daily_history()
        for changes in (
            {"currency": None},
            {"currency": "US"},
            {"currency": True},
            {"exchange_mic": None},
            {"exchange_mic": "Bad\nMIC"},
        ):
            result = self.result(replace(base, security=replace(base.security, **changes)))
            self.assertIsNone(result.close)
            self.assertEqual(result.volume, Decimal("120"))

    def test_invalid_financial_values_are_independently_withheld(self):
        base = daily_history()
        for value in (
            True,
            1,
            1.0,
            "1",
            Decimal("-1"),
            Decimal("NaN"),
            Decimal("sNaN"),
            Decimal("Infinity"),
            Decimal("1e25"),
            Decimal("0e-1000000"),
        ):
            row = replace(base.observations[0], close=value)
            result = self.result(replace(base, observations=(row,)))
            self.assertIsNone(result.close)
            self.assertEqual(result.volume, Decimal("120"))
            row = replace(base.observations[0], volume=value)
            result = self.result(replace(base, observations=(row,)))
            self.assertIsNone(result.volume)
            self.assertEqual(result.close, Decimal("30"))

    def test_field_specific_numeric_bounds(self):
        base = daily_history()
        for field, value in (
            ("close", Decimal("1e13")),
            ("close", Decimal("1e-19")),
            ("volume", Decimal("1e19")),
            ("volume", Decimal("1e-19")),
        ):
            row = replace(base.observations[0], **{field: value})
            self.assertIsNone(getattr(self.result(replace(base, observations=(row,))), field))

    def test_hostile_decimal_context_cannot_round_observed_inputs(self):
        with localcontext() as context:
            context.prec, context.Emax, context.Emin = 2, 1, -1
            for signal in context.traps:
                context.traps[signal] = True
            result = self.result(price_basis="adjusted", volume_basis="adjusted")
        self.assertEqual((result.close, result.volume), (Decimal("15"), Decimal("240.5")))

    def test_unsupported_bases_are_rejected_without_substitution(self):
        for price, volume in (("latest", "raw"), ("raw", "latest"), ([], "raw"), ("raw", None)):
            with self.assertRaises(ValueError):
                self.result(price_basis=price, volume_basis=volume)

    def test_preferences_form_accepts_only_supported_complete_choices(self):
        valid = {"price_basis": "raw", "volume_basis": "adjusted", "instrument_order": "ticker"}
        self.assertTrue(WatchlistPreferencesForm(valid).is_valid())
        for field in valid:
            self.assertFalse(WatchlistPreferencesForm({**valid, field: "invalid"}).is_valid())
            missing = {key: value for key, value in valid.items() if key != field}
            self.assertFalse(WatchlistPreferencesForm(missing).is_valid())


@skipUnless(connection.vendor == "postgresql", "Watchlist market persistence requires PostgreSQL")
class WatchlistMarketTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = get_user_model().objects.create_user("market-alice")
        cls.bob = get_user_model().objects.create_user("market-bob")
        cls.own = services.create_watchlist(user=cls.alice, name="Private daily research")
        cls.foreign = services.create_watchlist(user=cls.bob, name="Other owner secret")
        cls.items = tuple(
            WatchlistItem.objects.create(
                watchlist=cls.own,
                security_id=f"sec_watchlist_{n}",
                ticker=f"TST{n}",
                name="Synthetic company",
                currency="EUR",
                exchange_mic="XPAR",
                reference_retrieved_at=RETRIEVED,
            )
            for n in range(6)
        )
        cls.foreign_item = WatchlistItem.objects.create(
            watchlist=cls.foreign, security_id="sec_foreign", reference_retrieved_at=RETRIEVED
        )

    def setUp(self):
        self.client.force_login(self.alice)
        self.provider_patch = patch(
            "watchlists.market_services.market_data.daily_prices",
            side_effect=lambda identifier, day, address: daily_history(identifier, day),
        )
        self.provider = self.provider_patch.start()
        self.addCleanup(self.provider_patch.stop)
        _request_budget.reset()
        self.addCleanup(_request_budget.reset)

    def url(self, name="watchlist_market", watchlist=None):
        return reverse(name, args=[(watchlist or self.own).pk])

    def data(self, items=None, **changes):
        return {
            "market_date": "2020-01-02",
            "price_basis": "raw",
            "volume_basis": "raw",
            "items": [str(item.pk) for item in (items if items is not None else self.items[:2])],
            **changes,
        }

    def load(self, **changes):
        arguments = dict(
            user=self.alice,
            watchlist_id=self.own.pk,
            item_ids=tuple(item.pk for item in self.items[:2]),
            market_date=DAY,
            price_basis="raw",
            volume_basis="raw",
            client_address="market-client",
        )
        return load_market_information(**{**arguments, **changes})

    def save(self, **changes):
        return services.save_preferences(
            user=self.alice,
            watchlist_id=self.own.pk,
            **{
                "price_basis": "adjusted",
                "volume_basis": "raw",
                "instrument_order": "ticker",
                **changes,
            },
        )

    def test_blank_private_market_and_preferences_pages_never_request_data_or_write(self):
        before = list(Watchlist.objects.values())
        for name in ("watchlist_market", "watchlist_preferences", "watchlist_detail"):
            response = self.client.get(self.url(name))
            self.assertEqual(response.status_code, 200)
            self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(before, list(Watchlist.objects.values()))
        self.provider.assert_not_called()
        self.assertContains(self.client.get(self.url()), "No market data has been requested yet")

    def test_defaults_are_raw_raw_added_and_persist_on_explicit_save(self):
        self.assertEqual(
            (self.own.price_basis, self.own.volume_basis, self.own.instrument_order),
            ("raw", "raw", "added"),
        )
        response = self.client.post(
            self.url("watchlist_preferences"),
            {
                "price_basis": "adjusted",
                "volume_basis": "adjusted",
                "instrument_order": "ticker",
                "owner": self.bob.pk,
            },
        )
        self.assertRedirects(response, self.url("watchlist_detail"))
        self.own.refresh_from_db()
        self.assertEqual(
            (self.own.price_basis, self.own.volume_basis, self.own.instrument_order),
            ("adjusted", "adjusted", "ticker"),
        )
        self.foreign.refresh_from_db()
        self.assertEqual(self.foreign.price_basis, "raw")
        response = self.client.get(self.url())
        self.assertEqual(response.context["form"].initial["price_basis"], "adjusted")
        self.assertEqual(response.context["form"].initial["volume_basis"], "adjusted")
        self.provider.assert_not_called()

    def test_get_query_cannot_save_preferences_and_invalid_post_preserves_saved_values(self):
        self.client.get(self.url("watchlist_preferences"), {"price_basis": "adjusted"})
        response = self.client.post(
            self.url("watchlist_preferences"),
            {"price_basis": "invalid", "volume_basis": "raw", "instrument_order": "added"},
        )
        self.assertEqual(response.status_code, 400)
        self.own.refresh_from_db()
        self.assertEqual(self.own.price_basis, "raw")
        self.provider.assert_not_called()

    def test_preference_services_and_database_reject_invalid_choices(self):
        for field in ("price_basis", "volume_basis", "instrument_order"):
            with self.assertRaises(ValidationError):
                self.save(**{field: "invalid"})
            with self.assertRaises(IntegrityError), transaction.atomic():
                Watchlist.objects.filter(pk=self.own.pk).update(**{field: "invalid"})
        self.provider.assert_not_called()

    def test_ticker_order_is_case_insensitive_stable_and_nulls_last(self):
        for item, ticker in zip(
            self.items, ("Zulu", None, "beta", "ALPHA", "alpha", "Gamma"), strict=True
        ):
            WatchlistItem.objects.filter(pk=item.pk).update(ticker=ticker)
        self.save()
        self.own.refresh_from_db()
        ordered = list(services.ordered_items(self.own))
        self.assertEqual(
            [item.pk for item in ordered], [self.items[n].pk for n in (3, 4, 2, 5, 0, 1)]
        )
        response = self.client.get(self.url("watchlist_detail"))
        self.assertEqual(
            [item.pk for item in response.context["page"]], [item.pk for item in ordered]
        )

    def test_market_load_uses_response_currency_venue_and_keeps_old_bookmark(self):
        before = list(WatchlistItem.objects.values())
        response = self.client.get(self.url(), self.data())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "30 USD per share", count=2)
        self.assertContains(response, "XNYS · USD", count=2)
        self.assertContains(response, 'class="market-volume">120', count=2)
        self.assertContains(response, "2020-01-02")
        self.assertContains(response, "not live quotes")
        self.assertContains(response, "Retrieved: 2020-01-03")
        self.assertEqual(before, list(WatchlistItem.objects.values()))
        self.assertEqual(self.provider.call_count, 2)

    def test_one_load_overrides_saved_defaults_without_saving_them(self):
        self.save(price_basis="adjusted", volume_basis="adjusted")
        response = self.client.get(self.url(), self.data(items=self.items[:1]))
        self.assertContains(response, "30 USD per share")
        self.own.refresh_from_db()
        self.assertEqual((self.own.price_basis, self.own.volume_basis), ("adjusted", "adjusted"))

    def test_zero_and_fractional_counts_render_exactly(self):
        base = daily_history(self.items[0].security_id)
        self.provider.return_value = replace(
            base,
            observations=(
                replace(base.observations[0], close=Decimal("0"), volume=Decimal("0.125")),
            ),
        )
        self.provider.side_effect = None
        response = self.client.get(self.url(), self.data(items=self.items[:1]))
        self.assertContains(response, "0 USD per share")
        self.assertContains(response, 'class="market-volume">0.125')

    def test_over_limit_duplicate_empty_and_foreign_selections_make_no_requests(self):
        selections = (
            self.items,
            (),
            (self.items[0], self.items[0]),
            (self.foreign_item,),
            (self.items[0], self.foreign_item),
        )
        for selected in selections:
            response = self.client.get(self.url(), self.data(items=selected))
            self.assertEqual(response.status_code, 400)
            self.assertIn("no-store", response.headers["Cache-Control"])
            self.assertNotContains(
                response, 'class="price-panel watchlist-market-panel"', status_code=400
            )
        self.provider.assert_not_called()

    def test_bad_date_basis_or_missing_required_fields_make_no_requests(self):
        for changes in (
            {"market_date": "wrong"},
            {"market_date": "9999-01-01"},
            {"market_date": "1899-01-01"},
            {"price_basis": "live"},
            {"volume_basis": "usd"},
        ):
            self.assertEqual(self.client.get(self.url(), self.data(**changes)).status_code, 400)
        self.assertEqual(
            self.client.get(self.url(), {"market_date": "2020-01-02"}).status_code, 400
        )
        self.provider.assert_not_called()

    def test_direct_service_enforces_ownership_selection_bounds_and_input_validation(self):
        for ids in (
            (),
            tuple(item.pk for item in self.items),
            (self.items[0].pk, self.items[0].pk),
            ("bad",),
        ):
            with self.assertRaises(ValidationError):
                self.load(item_ids=ids)
        with self.assertRaises(services.WatchlistUnavailable):
            self.load(item_ids=(self.foreign_item.pk,))
        for changes in (
            {"price_basis": []},
            {"volume_basis": None},
            {"market_date": datetime.now(UTC)},
            {"market_date": datetime.now(UTC).date() + timedelta(days=1)},
        ):
            with self.assertRaises(ValidationError):
                self.load(**changes)
        self.provider.assert_not_called()

    def test_foreign_missing_and_forged_owner_routes_never_expose_data(self):
        for watchlist in (self.foreign, Watchlist(pk=uuid.uuid4())):
            for name in ("watchlist_market", "watchlist_preferences"):
                response = self.client.get(self.url(name, watchlist), self.data())
                self.assertEqual(response.status_code, 404)
                self.assertNotContains(response, self.foreign.name, status_code=404)
                self.assertIn("no-store", response.headers["Cache-Control"])
            response = self.client.post(
                self.url("watchlist_preferences", watchlist),
                {
                    "price_basis": "adjusted",
                    "volume_basis": "adjusted",
                    "instrument_order": "ticker",
                },
            )
            self.assertEqual(response.status_code, 404)
        self.provider.assert_not_called()

    def test_unauthenticated_and_method_errors_are_private(self):
        anonymous = Client()
        for name in ("watchlist_market", "watchlist_preferences"):
            url = self.url(name)
            response = anonymous.get(url, self.data())
            self.assertEqual(response.status_code, 302)
            self.assertIn("/sign-in/?next=", response.url)
            self.assertIn("no-store", response.headers["Cache-Control"])
            self.assertEqual(self.client.put(url).status_code, 405)
        self.assertEqual(self.client.post(self.url(), self.data()).status_code, 405)
        self.provider.assert_not_called()

    def test_csrf_is_required_for_saved_preferences(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.alice)
        url = self.url("watchlist_preferences")
        data = {"price_basis": "adjusted", "volume_basis": "adjusted", "instrument_order": "ticker"}
        response = client.post(url, data)
        self.assertEqual(response.status_code, 403)
        self.assertIn("no-store", response.headers["Cache-Control"])
        client.get(url)
        response = client.post(
            url, {**data, "csrfmiddlewaretoken": client.cookies["csrftoken"].value}
        )
        self.assertEqual(response.status_code, 302)
        self.own.refresh_from_db()
        self.assertEqual(self.own.price_basis, "adjusted")

    def test_per_item_provider_failure_preserves_other_successes_and_saved_records(self):
        self.provider.side_effect = [EntitlementDenied(), daily_history(self.items[1].security_id)]
        response = self.client.get(self.url(), self.data())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, EntitlementDenied.message)
        self.assertContains(response, "30 USD per share", count=1)
        self.assertEqual(len(response.context["rows"]), 2)
        self.assertEqual(WatchlistItem.objects.count(), 7)

    def test_rate_limit_stops_remaining_items_and_preserves_prior_values(self):
        self.provider.side_effect = [
            daily_history(self.items[0].security_id),
            ProviderRateLimited(37),
        ]
        response = self.client.get(self.url(), self.data(items=self.items[:3]))
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["Retry-After"], "37")
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertContains(response, "30 USD per share", status_code=429)
        self.assertContains(response, "Not requested after request limit", status_code=429)
        self.assertEqual(self.provider.call_count, 2)

    def test_missing_key_and_all_other_errors_are_fixed_per_item_messages(self):
        for error in (CredentialsMissing(), ProviderError()):
            self.provider.side_effect = error
            response = self.client.get(self.url(), self.data(items=self.items[:1]))
            self.assertContains(response, error.message)
            self.assertContains(response, 'class="market-close">Unavailable')

    def test_unexpected_failure_does_not_leak_authenticated_url_in_logs_or_page(self):
        secret = "synthetic-key-value"
        self.provider.side_effect = RuntimeError(f"https://example.invalid/?api_key={secret}")
        with self.assertLogs("research", level="ERROR") as logs:
            response = self.client.get(self.url(), self.data(items=self.items[:1]))
        self.assertNotIn(secret, response.content.decode())
        self.assertNotIn(secret, " ".join(logs.output))
        self.assertContains(response, ProviderError.message)

    def test_removal_during_request_discards_stale_authorized_result(self):
        def handler(identifier, day, address):
            self.items[0].delete()
            return daily_history(identifier, day)

        self.provider.side_effect = handler
        item_id = self.items[0].pk
        response = self.client.get(self.url(), self.data(items=self.items[:1]))
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, "30 USD per share", status_code=404)
        self.assertFalse(WatchlistItem.objects.filter(pk=item_id).exists())

    def test_owner_deactivation_during_request_discards_result(self):
        def handler(identifier, day, address):
            get_user_model().objects.filter(pk=self.alice.pk).update(is_active=False)
            return daily_history(identifier, day)

        self.provider.side_effect = handler
        response = self.client.get(self.url(), self.data(items=self.items[:1]))
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, "30 USD per share", status_code=404)

    @override_settings(INTRINIO_API_KEY=TEST_KEY)
    def test_actual_adapter_uses_one_request_per_item_same_date_no_reference_or_pagination(self):
        self.provider_patch.stop()
        requests = []

        def handler(request):
            requests.append(request)
            self.assertEqual(request.url.host, "api-v2.intrinio.com")
            self.assertEqual(request.url.params["start_date"], "2020-01-02")
            self.assertEqual(request.url.params["end_date"], "2020-01-02")
            self.assertNotIn("next_page", request.url.params)
            return daily_transport(request)

        with patch(
            "research.services.IntrinioClient",
            side_effect=lambda key: IntrinioClient(key, transport=httpx.MockTransport(handler)),
        ):
            rows, rate = self.load(item_ids=tuple(item.pk for item in self.items[:5]))
        self.assertEqual(len(requests), 5)
        self.assertEqual(len(rows), 5)
        self.assertIsNone(rate)
        self.assertTrue(all(row.observation.close == Decimal("30") for row in rows))
        self.assertTrue(all(request.url.path.endswith("/prices") for request in requests))

    @override_settings(INTRINIO_API_KEY=TEST_KEY)
    def test_actual_shared_budget_interrupts_load_without_requesting_remaining_items(self):
        self.provider_patch.stop()
        requests = []

        def handler(request):
            requests.append(request)
            return daily_transport(request)

        for _ in range(9):
            _reserve_request("market-client")
        with patch(
            "research.services.IntrinioClient",
            side_effect=lambda key: IntrinioClient(key, transport=httpx.MockTransport(handler)),
        ):
            rows, rate = self.load(item_ids=tuple(item.pk for item in self.items[:3]))
        self.assertEqual(len(requests), 1)
        self.assertIsInstance(rate, ProviderRateLimited)
        self.assertIsNotNone(rows[0].observation)
        self.assertIsInstance(rows[1].error, ProviderRateLimited)
        self.assertTrue(rows[2].not_requested)

    def test_rendered_names_are_escaped_and_preferences_remain_owner_scoped(self):
        WatchlistItem.objects.filter(pk=self.items[0].pk).update(
            name='<script>alert("fixture")</script>'
        )
        response = self.client.get(self.url(), self.data(items=self.items[:1]))
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, '<script>alert("fixture")</script>')
        self.assertNotContains(response, self.foreign.name)


class WatchlistMarketStorageTests(TestCase):
    def test_storage_guard_precedes_lookup_provider_and_preferences_write(self):
        user = get_user_model().objects.create_user("market-storage-check")
        self.client.force_login(user)
        with (
            patch("watchlists.services.connection") as database,
            patch("watchlists.market_services.market_data.daily_prices") as provider,
        ):
            database.vendor = "sqlite"
            for name in ("watchlist_market", "watchlist_preferences"):
                url = reverse(name, args=[uuid.uuid4()])
                response = self.client.get(url)
                self.assertContains(
                    response, "Watchlist storage is not configured", status_code=503
                )
                self.assertIn("no-store", response.headers["Cache-Control"])
            self.assertEqual(self.client.post(url, {}).status_code, 503)
            provider.assert_not_called()


@skipUnless(connection.vendor == "postgresql", "Migration/network lock checks require PostgreSQL")
class WatchlistMarketTransactionTests(TransactionTestCase):
    def test_provider_io_does_not_hold_an_application_transaction(self):
        user = get_user_model().objects.create_user("market-unlocked")
        watchlist = services.create_watchlist(user=user, name="No network lock")
        item = WatchlistItem.objects.create(
            watchlist=watchlist, security_id="sec_watchlist_0", reference_retrieved_at=RETRIEVED
        )

        def handler(identifier, day, address):
            self.assertFalse(connection.in_atomic_block)
            return daily_history(identifier, day)

        with patch("watchlists.market_services.market_data.daily_prices", side_effect=handler):
            rows, _ = load_market_information(
                user=user,
                watchlist_id=watchlist.pk,
                item_ids=(item.pk,),
                market_date=DAY,
                price_basis="raw",
                volume_basis="raw",
                client_address="market-unlocked",
            )
        self.assertEqual(rows[0].observation.close, Decimal("30"))

    def test_additive_migration_preserves_existing_watchlist_and_reference_snapshot(self):
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate([("watchlists", "0001_initial")])
            historical = executor.loader.project_state([("watchlists", "0001_initial")]).apps
            user = historical.get_model("accounts", "User").objects.create(
                username="before-preferences"
            )
            watchlist = historical.get_model("watchlists", "Watchlist").objects.create(
                owner_id=user.pk, name="Existing list"
            )
            item = historical.get_model("watchlists", "WatchlistItem").objects.create(
                watchlist_id=watchlist.pk,
                security_id="sec_prior",
                ticker="PRIOR",
                reference_retrieved_at=RETRIEVED,
            )
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
            current = Watchlist.objects.get(pk=watchlist.pk)
            self.assertEqual(
                (current.price_basis, current.volume_basis, current.instrument_order),
                ("raw", "raw", "added"),
            )
            current_item = WatchlistItem.objects.get(pk=item.pk)
            self.assertEqual(
                (
                    current_item.security_id,
                    current_item.ticker,
                    current_item.reference_retrieved_at,
                ),
                ("sec_prior", "PRIOR", RETRIEVED),
            )
        finally:
            MigrationExecutor(connection).migrate(latest)
