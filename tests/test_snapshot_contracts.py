"""Synthetic contracts, bounded resolution, private persistence and retry races."""

import copy
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.http import Http404
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from market_data.contracts import SearchResult, Security, SecurityResult
from market_data.errors import InvalidResponse, ProviderError, ProviderRateLimited
from portfolios import snapshot_previews as previews
from portfolios import snapshot_resolution as resolution
from portfolios import snapshot_services as services
from portfolios.holdings_forms import HoldingsPreviewForm
from portfolios.models import HoldingsSnapshot, SnapshotHolding, SnapshotSubmission
from research import services as market_data
from tests.test_holdings_csv import HEADER, VALID, upload

NOW = timezone.now()
SECURITY = Security("sec_snapshot_one", "TSTF", "Synthetic company", "XNAS", "USD")
SEARCH = SearchResult((SECURITY,), NOW)
REFERENCE = SecurityResult(SECURITY, NOW)


def initial(user, *, cash_only=False):
    form = HoldingsPreviewForm(
        {"name": "Synthetic snapshot", "as_of": "2020-01-02", "cash": "12.34"},
        {"holdings_file": upload(HEADER if cash_only else VALID)},
    )
    if not form.is_valid():
        raise AssertionError(form.errors)
    return previews.start(form.cleaned_data, user)


def matched(user, *, cash_only=False):
    payload = initial(user, cash_only=cash_only)
    payload["stage"] = "matches"
    for row in payload["rows"]:
        row["choices"] = [resolution.reference(SECURITY, NOW, row)]
    return payload


def verified(user, *, cash_only=False):
    payload = matched(user, cash_only=cash_only)
    payload["stage"] = "verified"
    for row in payload["rows"]:
        row["reference"] = copy.deepcopy(row["choices"][0])
    return payload


def raw_token(payload):
    return signing.dumps(payload, salt=previews.SALT)


class PreviewContractTests(SimpleTestCase):
    def setUp(self):
        self.user = get_user_model()(pk=1, username="synthetic", is_active=True)
        self.payload = verified(self.user)

    def test_round_trip_preserves_exact_values_and_original_expiry(self):
        token = previews.encode(self.payload, self.user)
        loaded = previews.decode(token, self.user, stage="verified")
        self.assertEqual(loaded["rows"][0]["quantity"], "1.000001")
        with patch(
            "portfolios.snapshot_previews.time.time", return_value=self.payload["issued"] + 899
        ):
            refreshed = previews.encode(loaded, self.user)
        with patch(
            "portfolios.snapshot_previews.time.time", return_value=self.payload["issued"] + 901
        ):
            with self.assertRaises(ValidationError):
                previews.decode(refreshed, self.user)

    def test_signature_owner_stage_size_compression_and_activity_checked(self):
        token = previews.encode(self.payload, self.user)
        other = get_user_model()(pk=2, is_active=True)
        for value in (
            token + "x",
            "",
            "x" * (previews.MAX_TOKEN + 1),
            signing.dumps(self.payload, salt=previews.SALT, compress=True),
        ):
            with self.subTest(value=value[:20]), self.assertRaises(ValidationError):
                previews.decode(value, self.user)
        with self.assertRaises(ValidationError):
            previews.decode(token, other)
        with self.assertRaises(ValidationError):
            previews.decode(token, self.user, stage="input")
        for user in (AnonymousUser(), get_user_model()(pk=1, is_active=False)):
            with self.assertRaises(PermissionDenied):
                previews.decode(token, user)

    def test_signed_but_invalid_structure_metadata_or_references_are_rejected(self):
        variants = []
        for key, values in {
            "version": [True, 2],
            "issued": [True, int(time.time()) + 3600, 0],
            "key": ["invalid", 123],
            "name": ["", " x ", "bad\nname", "x" * 101],
            "as_of": ["2020-01-04", "1999-12-31", "2099-01-02"],
            "cash": ["", "-1", "NaN", "1e2", "1.001", "1000000000001"],
            "rows": [None, [{}], self.payload["rows"] * 6],
        }.items():
            for value in values:
                payload = copy.deepcopy(self.payload)
                payload[key] = value
                variants.append(payload)
        for field, value in (
            ("quantity", "0"),
            ("quantity", "0.0000001"),
            ("ticker", " TSTF"),
            ("currency", "EUR"),
            ("choices", []),
            ("reference", None),
        ):
            payload = copy.deepcopy(self.payload)
            payload["rows"][0][field] = value
            variants.append(payload)
        for field, value in (
            ("security_id", "bad/id"),
            ("ticker", "OTHER"),
            ("currency", "EUR"),
            ("exchange_mic", "XNYS"),
            ("name", "bad\nname"),
            ("retrieved_at", "2020-01-02T12:00:00"),
            ("retrieved_at", "2099-01-02T12:00:00+00:00"),
        ):
            payload = copy.deepcopy(self.payload)
            payload["rows"][0]["reference"][field] = value
            variants.append(payload)
        for payload in [[], {}, None, *variants]:
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                previews.decode(raw_token(payload), self.user)

    def test_cash_only_requires_positive_cash_and_duplicate_rows_fail(self):
        payload = verified(self.user, cash_only=True)
        self.assertEqual(previews.decode(raw_token(payload), self.user)["rows"], [])
        payload["cash"] = "0"
        with self.assertRaises(ValidationError):
            previews.decode(raw_token(payload), self.user)
        self.payload["rows"] *= 2
        with self.assertRaises(ValidationError):
            previews.decode(raw_token(self.payload), self.user)


class ResolutionTests(SimpleTestCase):
    def setUp(self):
        self.user = get_user_model()(pk=1, is_active=True)

    def test_explicit_exact_selection_then_separate_reference_lookup(self):
        with (
            patch.object(market_data, "search_securities", return_value=SEARCH) as search,
            patch.object(market_data, "security_details", return_value=REFERENCE) as details,
        ):
            payload, issues, error = resolution.find_matches(
                initial(self.user), self.user, "client"
            )
            search.assert_called_once_with("TSTF", "client")
            details.assert_not_called()
            self.assertEqual(issues, [])
            self.assertIsNone(error)
            with self.assertRaises(ValidationError):
                resolution.validate_selections(payload, [""], self.user, "client")
            with self.assertRaises(ValidationError):
                resolution.validate_selections(payload, ["substituted"], self.user, "client")
            details.assert_not_called()
            verified_payload = resolution.validate_selections(
                payload, [SECURITY.id], self.user, "client"
            )
            details.assert_called_once_with(SECURITY.id, "client")
            self.assertEqual(verified_payload["stage"], "verified")
            self.assertIsNone(payload["rows"][0]["reference"])

    def test_truncated_nonexact_and_excess_ambiguous_matches_stay_unresolved(self):
        for result in (
            SearchResult((SECURITY,), NOW, pagination_complete=False),
            SearchResult((Security("other", "tstf", "Other", "XNAS", "USD"),), NOW),
            SearchResult((Security("other", "TSTF", "Other", "XNYS", "USD"),), NOW),
            SearchResult((Security("other", "TSTF", "Other", "XNAS", "EUR"),), NOW),
            SearchResult(
                tuple(Security(f"id{i}", "TSTF", "Other", "XNAS", "USD") for i in range(6)), NOW
            ),
        ):
            with (
                self.subTest(result=result),
                patch.object(market_data, "search_securities", return_value=result),
            ):
                payload, issues, error = resolution.find_matches(
                    initial(self.user), self.user, "client"
                )
                self.assertFalse(payload["rows"][0]["choices"])
                self.assertTrue(issues)
                self.assertIsNone(error)

    def test_reference_identity_currency_venue_timestamp_and_label_must_validate(self):
        for result in (
            SecurityResult(Security("other", "TSTF", "Other", "XNAS", "USD"), NOW),
            SecurityResult(Security(SECURITY.id, "OTHER", "Other", "XNAS", "USD"), NOW),
            SecurityResult(Security(SECURITY.id, "TSTF", "Other", "XNYS", "USD"), NOW),
            SecurityResult(Security(SECURITY.id, "TSTF", "Other", "XNAS", "EUR"), NOW),
            SecurityResult(Security(SECURITY.id, "TSTF", "bad\nname", "XNAS", "USD"), NOW),
            SecurityResult(SECURITY, NOW.replace(tzinfo=None)),
        ):
            with (
                self.subTest(result=result),
                patch.object(market_data, "security_details", return_value=result),
                self.assertRaises(InvalidResponse),
            ):
                resolution.validate_selections(
                    matched(self.user), [SECURITY.id], self.user, "client"
                )

    def five(self, stage="input"):
        payload = initial(self.user)
        payload["rows"] = [copy.deepcopy(payload["rows"][0]) for _ in range(5)]
        for i, row in enumerate(payload["rows"]):
            row["ticker"] = f"TEST{i}"
            if stage == "matches":
                security = Security(f"sec{i}", row["ticker"], "Synthetic", "XNAS", "USD")
                row["choices"] = [resolution.reference(security, NOW, row)]
        payload["stage"] = stage
        return payload

    def test_five_request_ceiling_shared_budget_and_429_stop(self):
        payload = self.five()

        def search(query, address):
            return SearchResult(
                (Security("sec" + query[-1], query, "Synthetic", "XNAS", "USD"),), NOW
            )

        with patch.object(market_data, "search_securities", side_effect=search) as request:
            payload, issues, error = resolution.find_matches(payload, self.user, "client")
            self.assertEqual(request.call_count, 5)
            self.assertFalse(issues)
            self.assertIsNone(error)
            # An explicit search retry preserves matches and spends no extra requests.
            resolution.find_matches(payload, self.user, "client")
            self.assertEqual(request.call_count, 5)
        with patch.object(
            market_data,
            "security_details",
            side_effect=lambda sid, address: SecurityResult(
                Security(sid, "TEST" + sid[-1], "Synthetic", "XNAS", "USD"), NOW
            ),
        ) as request:
            resolution.validate_selections(
                payload, [f"sec{i}" for i in range(5)], self.user, "client"
            )
            self.assertEqual(request.call_count, 5)
        with patch.object(
            market_data,
            "search_securities",
            side_effect=[search("TEST0", "client"), ProviderRateLimited(12)],
        ) as request:
            partial, _, error = resolution.find_matches(self.five(), self.user, "client")
            self.assertEqual(request.call_count, 2)
            self.assertEqual(error.retry_after, 12)
            self.assertTrue(partial["rows"][0]["choices"])
            self.assertFalse(partial["rows"][1]["choices"])
        with (
            patch.object(
                market_data, "security_details", side_effect=ProviderRateLimited(8)
            ) as request,
            self.assertRaises(ProviderRateLimited),
        ):
            resolution.validate_selections(
                payload, [f"sec{i}" for i in range(5)], self.user, "client"
            )
        self.assertEqual(request.call_count, 1)

    @override_settings(INTRINIO_API_KEY="synthetic", RATE_LIMIT_BACKEND="memory")
    def test_resolution_uses_the_same_admission_budget_as_research(self):
        market_data._request_budget.reset()
        self.addCleanup(market_data._request_budget.reset)
        for _ in range(9):
            market_data._request_budget.reserve("client")
        with patch("research.services.IntrinioClient") as provider:
            provider.return_value.__enter__.return_value.search.return_value = SEARCH
            payload, _, error = resolution.find_matches(initial(self.user), self.user, "client")
            self.assertIsNone(error)
            with self.assertRaises(ProviderRateLimited):
                resolution.validate_selections(payload, [SECURITY.id], self.user, "client")
            provider.return_value.__enter__.return_value.security.assert_not_called()

    def test_duplicate_resolved_ids_fail_before_reference_requests(self):
        payload = self.five(stage="matches")
        for row in payload["rows"]:
            row["choices"][0]["security_id"] = "same_id"
        with patch.object(market_data, "security_details") as details:
            with self.assertRaisesMessage(ValidationError, "same instrument"):
                resolution.validate_selections(payload, ["same_id"] * 5, self.user, "client")
            details.assert_not_called()

    def test_cash_only_and_invalid_context_spend_no_requests_and_errors_are_safe(self):
        with (
            patch.object(market_data, "search_securities") as search,
            patch.object(market_data, "security_details") as details,
        ):
            payload, _, _ = resolution.find_matches(
                initial(self.user, cash_only=True), self.user, "client"
            )
            resolution.validate_selections(payload, [], self.user, "client")
            search.assert_not_called()
            details.assert_not_called()
        with (
            patch.object(market_data, "search_securities", side_effect=RuntimeError("SECRET")),
            self.assertLogs("research", level="ERROR") as logs,
        ):
            _, _, error = resolution.find_matches(initial(self.user), self.user, "client")
        self.assertIsInstance(error, ProviderError)
        self.assertNotIn("SECRET", str(logs.output) + str(error))


@skipUnless(connection.vendor == "postgresql", "Snapshots require PostgreSQL")
class SnapshotStorageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = get_user_model().objects.create_user("snapshot-alice")
        cls.bob = get_user_model().objects.create_user("snapshot-bob")

    def setUp(self):
        self.payload = verified(self.alice)
        self.token = previews.encode(self.payload, self.alice)

    def save(self, **kwargs):
        return services.save_snapshot(user=self.alice, token=self.token, confirmed=True, **kwargs)

    def test_save_is_atomic_exact_and_idempotent_without_ledger_activity(self):
        from django.test.utils import CaptureQueriesContext

        with (
            patch("httpx.Client.send", side_effect=AssertionError("Unexpected provider call")),
            CaptureQueriesContext(connection) as queries,
        ):
            first, second = self.save(), self.save()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(HoldingsSnapshot.objects.count(), 1)
        self.assertEqual(first.holdings.get().quantity, Decimal("1.000001"))
        self.assertEqual(first.cash, "12.34")
        self.assertEqual(SnapshotSubmission.objects.count(), 1)
        for query in queries:
            self.assertNotRegex(query["sql"], r"(?i)(ledger_|watchlists_|portfolios_portfolio)")

    def test_failure_rolls_back_parent_rows_and_receipt(self):
        with (
            patch.object(SnapshotSubmission.objects, "create", side_effect=IntegrityError("test")),
            self.assertRaises(IntegrityError),
        ):
            self.save()
        self.assertEqual(HoldingsSnapshot.objects.count(), 0)
        self.assertEqual(SnapshotHolding.objects.count(), 0)
        self.assertEqual(SnapshotSubmission.objects.count(), 0)

    def test_revalidation_confirmation_owner_and_activity(self):
        for user, confirmed, error in (
            (self.bob, True, ValidationError),
            (self.alice, False, ValidationError),
            (AnonymousUser(), True, PermissionDenied),
        ):
            with self.assertRaises(error):
                services.save_snapshot(user=user, token=self.token, confirmed=confirmed)
        get_user_model().objects.filter(pk=self.alice.pk).update(is_active=False)
        # Stale authenticated object cannot bypass the database owner check.
        with self.assertRaises(PermissionDenied):
            self.save()
        self.assertFalse(HoldingsSnapshot.objects.exists())

    def test_conflicting_key_rejected_new_key_allowed_and_canonical_retry_matches(self):
        first = self.save()
        altered = copy.deepcopy(self.payload)
        altered["cash"] = "12.340"  # excess precision is invalid even if mathematically equal
        with self.assertRaises(ValidationError):
            services.save_snapshot(user=self.alice, token=raw_token(altered), confirmed=True)
        altered["cash"] = "13.00"
        with self.assertRaisesMessage(ValidationError, "different inputs"):
            services.save_snapshot(user=self.alice, token=raw_token(altered), confirmed=True)
        same = copy.deepcopy(self.payload)
        same["rows"][0]["reference"]["name"] = "Updated reference label"
        self.assertEqual(
            services.save_snapshot(user=self.alice, token=raw_token(same), confirmed=True).pk,
            first.pk,
        )
        altered["key"] = str(uuid.uuid4())
        self.assertNotEqual(
            services.save_snapshot(user=self.alice, token=raw_token(altered), confirmed=True).pk,
            first.pk,
        )

    def test_deletion_is_private_and_stale_retry_cannot_restore_snapshot(self):
        snapshot = self.save()
        for who, pk in ((self.bob, snapshot.pk), (self.alice, uuid.uuid4())):
            with self.assertRaises(Http404):
                services.delete_snapshot(user=who, snapshot_id=pk)
        services.delete_snapshot(user=self.alice, snapshot_id=snapshot.pk)
        self.assertFalse(SnapshotHolding.objects.exists())
        receipt = SnapshotSubmission.objects.get()
        self.assertIsNone(receipt.snapshot_id)
        self.assertEqual(
            set(field.name for field in receipt._meta.fields),
            {"id", "owner", "key", "digest", "expires_at", "snapshot"},
        )
        with self.assertRaisesMessage(ValidationError, "deleted"):
            self.save()
        SnapshotSubmission.objects.filter(pk=receipt.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        new = verified(self.alice, cash_only=True)
        services.save_snapshot(user=self.alice, token=raw_token(new), confirmed=True)
        self.assertFalse(SnapshotSubmission.objects.filter(pk=receipt.pk).exists())

    def test_expiry_is_rechecked_after_waiting_for_owner_lock(self):
        original = services.lock_owner

        def expire_after_lock(user):
            original(user)
            self.clock.return_value = self.payload["issued"] + previews.LIFETIME + 1

        with patch(
            "portfolios.snapshot_previews.time.time", return_value=self.payload["issued"]
        ) as self.clock:
            with patch.object(services, "lock_owner", side_effect=expire_after_lock):
                with self.assertRaises(ValidationError):
                    self.save()
        self.assertFalse(HoldingsSnapshot.objects.exists())
        self.assertFalse(SnapshotSubmission.objects.exists())

    def test_capacity_and_same_submission_retry_at_capacity(self):
        with patch.object(services, "MAX_SNAPSHOTS", 1):
            first = self.save()
            self.assertEqual(self.save().pk, first.pk)
            with self.assertRaisesMessage(ValidationError, "up to 50"):
                services.save_snapshot(
                    user=self.alice, token=raw_token(verified(self.alice)), confirmed=True
                )
        self.assertEqual(HoldingsSnapshot.objects.count(), 1)

    def test_database_rejects_invalid_cash_quantity_currency_and_duplicate_identity(self):
        snapshot = self.save()
        holding = snapshot.holdings.get()
        for model, pk, changes in (
            (HoldingsSnapshot, snapshot.pk, {"cash": -1}),
            (HoldingsSnapshot, snapshot.pk, {"cash": 1000000000001}),
            (HoldingsSnapshot, snapshot.pk, {"currency": "EUR"}),
            (HoldingsSnapshot, snapshot.pk, {"confirmation_version": 2}),
            (SnapshotHolding, holding.pk, {"quantity": 0}),
            (SnapshotHolding, holding.pk, {"quantity": 1000000001}),
            (SnapshotHolding, holding.pk, {"currency": "EUR"}),
        ):
            with (
                self.subTest(changes=changes),
                self.assertRaises(IntegrityError),
                transaction.atomic(),
            ):
                model.objects.filter(pk=pk).update(**changes)
        holding.pk = None
        with self.assertRaises(IntegrityError), transaction.atomic():
            holding.save(force_insert=True)


@skipUnless(connection.vendor == "postgresql", "Snapshot races require PostgreSQL")
class SnapshotConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("snapshot-race")
        self.payload = verified(self.user)
        self.token = raw_token(self.payload)

    def race(self, operations):
        barrier = Barrier(len(operations))

        def run(operation):
            close_old_connections()
            try:
                user = get_user_model().objects.get(pk=self.user.pk)
                barrier.wait(timeout=10)
                try:
                    return operation(user)
                except (ValidationError, Http404) as error:
                    return type(error)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=len(operations)) as pool:
            return list(pool.map(run, operations))

    def test_identical_concurrent_save_creates_one_row_set(self):
        def save(user):
            return services.save_snapshot(user=user, token=self.token, confirmed=True).pk

        results = self.race([save, save])
        self.assertEqual(results[0], results[1])
        self.assertEqual(HoldingsSnapshot.objects.count(), 1)
        self.assertEqual(SnapshotHolding.objects.count(), 1)
        self.assertEqual(SnapshotSubmission.objects.count(), 1)

    def test_capacity_race_and_conflicting_key_race(self):
        other = verified(self.user)
        with patch.object(services, "MAX_SNAPSHOTS", 1):
            result = self.race(
                [
                    lambda user: (
                        services.save_snapshot(user=user, token=self.token, confirmed=True).pk
                    ),
                    lambda user: (
                        services.save_snapshot(user=user, token=raw_token(other), confirmed=True).pk
                    ),
                ]
            )
        self.assertEqual(result.count(ValidationError), 1)
        self.assertEqual(HoldingsSnapshot.objects.count(), 1)
        HoldingsSnapshot.objects.all().delete()
        SnapshotSubmission.objects.all().delete()
        altered = copy.deepcopy(self.payload)
        altered["cash"] = "20"
        result = self.race(
            [
                lambda user: services.save_snapshot(user=user, token=self.token, confirmed=True).pk,
                lambda user: (
                    services.save_snapshot(user=user, token=raw_token(altered), confirmed=True).pk
                ),
            ]
        )
        self.assertEqual(result.count(ValidationError), 1)
        self.assertEqual(HoldingsSnapshot.objects.count(), 1)

    def test_delete_racing_save_retry_never_resurrects_inputs(self):
        saved = services.save_snapshot(user=self.user, token=self.token, confirmed=True)
        self.race(
            [
                lambda user: services.delete_snapshot(user=user, snapshot_id=saved.pk),
                lambda user: services.save_snapshot(user=user, token=self.token, confirmed=True).pk,
            ]
        )
        self.assertFalse(HoldingsSnapshot.objects.exists())
        self.assertFalse(SnapshotHolding.objects.exists())
        with self.assertRaisesMessage(ValidationError, "deleted"):
            services.save_snapshot(user=self.user, token=self.token, confirmed=True)
