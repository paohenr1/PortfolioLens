"""Actual PostgreSQL action constraints, atomic appends, ownership and schema preservation."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from ledger.fifo import analyze
from ledger.models import Entry
from ledger.services import append_entry
from market_data.errors import CredentialsMissing
from portfolios.services import create_portfolio
from tests.test_actions import dividend, split
from tests.test_ledger import REFERENCE
from tests.test_ledger_domain import DAY, cash, trade

D = Decimal


@skipUnless(connection.vendor == "postgresql", "Corporate actions require PostgreSQL")
class ActionStorageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user("actions-owner")
        cls.other = get_user_model().objects.create_user("actions-other")
        cls.portfolio = create_portfolio(owner=cls.owner, name="Action example")
        cls.foreign = create_portfolio(owner=cls.other, name="Foreign actions")

    def setUp(self):
        self.client.force_login(self.owner)
        self.provider = patch(
            "ledger.services.market_data.security_details", return_value=REFERENCE
        ).start()
        self.addCleanup(patch.stopall)
        self.record(cash())
        self.record(trade())
        self.provider.reset_mock()

    def record(self, event, key=None):
        return append_entry(
            user=self.owner,
            portfolio_id=self.portfolio.pk,
            client_key=key or uuid.uuid4(),
            intent=event,
            client_address="127.0.0.1",
        )

    def test_action_rows_round_trip_and_reconcile_fifo_and_income(self):
        entry = self.record(split())
        self.record(dividend(sequence=4))
        self.record(trade("SELL", "8", "15", "2", 5))
        entry.refresh_from_db()
        self.assertEqual(entry.as_input(), split())
        self.assertEqual(entry.amount, D("0.00"))
        self.assertEqual(entry.cash_delta, D("0"))
        self.assertEqual(entry.reference_retrieved_at, REFERENCE.retrieved_at)
        result = analyze([row.as_input() for row in Entry.objects.all()])
        self.assertEqual(result.cash, D("872.00"))
        self.assertEqual(result.net_dividends, D("5.00"))
        self.assertEqual(result.open_cost_basis, D("150.60"))
        self.assertEqual(result.realized_gain, D("17.60"))
        self.assertEqual(self.provider.call_count, 3)

    def test_action_retry_has_no_lookup_and_changed_ratio_key_is_rejected(self):
        key = uuid.uuid4()
        original = self.record(split(), key)
        self.provider.reset_mock()
        self.assertEqual(self.record(split(), key).pk, original.pk)
        with self.assertRaises(ValidationError):
            self.record(split(3, 1), key)
        self.provider.assert_not_called()
        self.assertEqual(Entry.objects.count(), 3)

    def test_unsupported_per_lot_split_is_rejected_before_provider_and_preserves_rows(self):
        self.record(trade("SELL", "9", "30", "0", 3))
        self.provider.reset_mock()
        before = list(Entry.objects.values())
        with self.assertRaisesMessage(ValidationError, "cash-in-lieu"):
            self.record(split(1, 3, 4))
        self.provider.assert_not_called()
        self.assertEqual(list(Entry.objects.values()), before)

    def test_backdated_reverse_split_cannot_invalidate_later_sale(self):
        self.record(trade("SELL", "8", "30", "0", 4))
        self.provider.reset_mock()
        with self.assertRaisesMessage(ValidationError, "short position"):
            self.record(split(1, 2, 3))
        self.assertEqual(Entry.objects.count(), 3)
        self.provider.assert_not_called()

    def test_action_form_csrf_owner_isolation_and_shape_checks(self):
        url = reverse("ledger_create", args=[self.portfolio.pk])
        payload = {
            "kind": "SPLIT",
            "currency": "USD",
            "event_date": "2020-01-02",
            "sequence": "3",
            "security_id": "sec_fixture_primary",
            "fees": "0",
            "split_new": "2",
            "split_old": "1",
            "client_key": str(uuid.uuid4()),
        }
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.owner)
        self.assertEqual(protected.post(url, payload).status_code, 403)
        foreign = self.client.post(reverse("ledger_create", args=[self.foreign.pk]), payload)
        self.assertEqual(foreign.status_code, 404)
        for changes in (
            {"amount": "1"},
            {"split_new": "0"},
            {"quantity": "1"},
            {"kind": "DIVIDEND", "amount": "5"},
        ):
            response = self.client.post(url, {**payload, **changes})
            self.assertTrue(response.context["form"].errors)
        self.provider.assert_not_called()
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Entry.objects.filter(kind="SPLIT").count(), 1)

    def test_provider_failure_cannot_record_an_action(self):
        self.provider.side_effect = CredentialsMissing()
        response = self.client.post(
            reverse("ledger_create", args=[self.portfolio.pk]),
            {
                "kind": "DIVIDEND",
                "currency": "USD",
                "event_date": "2020-01-02",
                "sequence": "3",
                "security_id": "sec_fixture_primary",
                "amount": "5",
                "client_key": str(uuid.uuid4()),
            },
        )
        self.assertContains(response, "No transaction was recorded", status_code=503)
        self.assertEqual(Entry.objects.count(), 2)

    def test_database_rejects_bad_null_equal_ratio_and_action_shapes(self):
        valid = {
            "portfolio": self.portfolio,
            "kind": "SPLIT",
            "event_date": DAY,
            "sequence": 3,
            "amount": D("0"),
            "security_id": "sec_fixture_primary",
            "security_ticker": "TSTF",
            "exchange_mic": "XNYS",
            "reference_retrieved_at": REFERENCE.retrieved_at,
            "split_new": 2,
            "split_old": 1,
        }
        for changes in (
            {"split_new": None},
            {"split_old": None},
            {"split_old": 2},
            {"split_new": 0},
            {"split_new": 1000001},
            {"amount": D("1")},
            {"fees": D("1")},
            {"quantity": D("1")},
            {"security_id": ""},
            {"kind": "DIVIDEND", "amount": D("5")},
            {"kind": "DEPOSIT"},
        ):
            with (
                self.subTest(changes=changes),
                self.assertRaises(IntegrityError),
                transaction.atomic(),
            ):
                Entry.objects.create(**{**valid, **changes}, client_key=uuid.uuid4())

    def test_actions_remain_immutable_and_ui_reports_ratio_income_and_lot_units(self):
        entry = self.record(split())
        self.record(dividend(sequence=4))
        with self.assertRaises(IntegrityError), transaction.atomic():
            Entry.objects.filter(pk=entry.pk).update(split_new=3)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Entry.objects.filter(pk=entry.pk).delete()
        self.provider.reset_mock()
        history = self.client.get(reverse("ledger_history", args=[self.portfolio.pk]))
        self.assertContains(history, "2 for 1")
        self.assertContains(history, "Dividend")
        positions = self.client.get(reverse("portfolio_positions", args=[self.portfolio.pk]))
        self.assertEqual(positions.context["analysis"].net_dividends, D("5.00"))
        self.assertEqual(positions.context["analysis"].positions[0].quantity, D("20"))
        self.assertIn("no-store", positions.headers["Cache-Control"])
        self.provider.assert_not_called()


@skipUnless(connection.vendor == "postgresql", "Action races require PostgreSQL")
class ActionConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("actions-race")
        self.portfolio = create_portfolio(owner=self.owner, name="Split race")
        self.provider = patch(
            "ledger.services.market_data.security_details", return_value=REFERENCE
        ).start()
        self.addCleanup(patch.stopall)
        self.record(cash(), uuid.uuid4())
        self.record(trade(), uuid.uuid4())

    def record(self, event, key):
        return append_entry(
            user=self.owner,
            portfolio_id=self.portfolio.pk,
            client_key=key,
            intent=event,
            client_address="127.0.0.1",
        )

    def race(self, keys):
        barrier = Barrier(2)

        def submit(key):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                try:
                    return self.record(split(), key).pk
                except ValidationError:
                    return None
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            return list(executor.map(submit, keys))

    def test_concurrent_duplicate_split_is_applied_once(self):
        key = uuid.uuid4()
        results = self.race((key, key))
        self.assertEqual(results[0], results[1])
        self.assertIsNotNone(results[0])
        self.assertEqual(Entry.objects.filter(kind="SPLIT").count(), 1)
        self.assertEqual(
            analyze([row.as_input() for row in Entry.objects.all()]).positions[0].quantity, D("20")
        )

    def test_duplicate_commit_between_initial_key_check_and_preflight_returns_existing(self):
        from ledger.services import retry_entry

        key = uuid.uuid4()
        first_check = True
        committed = None

        def check_with_commit(portfolio, client_key, intent):
            nonlocal first_check, committed
            existing = retry_entry(portfolio, client_key, intent)
            if first_check:
                first_check = False
                self.assertIsNone(existing)
                # Deterministically place a committed identical request in the
                # gap before the caller reads its unlocked journal snapshot.
                committed = self.record(split(), key)
            return existing

        with patch("ledger.services.retry_entry", side_effect=check_with_commit):
            result = self.record(split(), key)
        self.assertEqual(result.pk, committed.pk)
        self.assertEqual(Entry.objects.filter(kind="SPLIT").count(), 1)
        self.assertEqual(
            analyze([row.as_input() for row in Entry.objects.all()]).positions[0].quantity, D("20")
        )

    def test_concurrent_distinct_keys_cannot_record_same_split_order_twice(self):
        results = self.race((uuid.uuid4(), uuid.uuid4()))
        self.assertEqual(results.count(None), 1)
        self.assertEqual(Entry.objects.filter(kind="SPLIT").count(), 1)


@skipUnless(connection.vendor == "postgresql", "Upgrade preservation requires PostgreSQL")
class ActionMigrationTests(TransactionTestCase):
    def test_upgrade_preserves_existing_journal_and_keeps_trigger_installed(self):
        executor = MigrationExecutor(connection)
        old_target = [("ledger", "0002_immutable_entries")]
        new_target = executor.loader.graph.leaf_nodes("ledger")
        executor.migrate(old_target)
        try:
            old_apps = executor.loader.project_state(old_target).apps
            user = old_apps.get_model("accounts", "User").objects.create(username="migration-owner")
            portfolio = old_apps.get_model("portfolios", "Portfolio").objects.create(
                owner_id=user.pk, name="Preserved journal"
            )
            old_entry = old_apps.get_model("ledger", "Entry").objects.create(
                portfolio_id=portfolio.pk,
                client_key=uuid.uuid4(),
                kind="DEPOSIT",
                event_date=DAY,
                sequence=1,
                amount=D("123.45"),
            )
            old_apps.get_model("ledger", "Entry").objects.create(
                portfolio_id=portfolio.pk,
                client_key=uuid.uuid4(),
                kind="BUY",
                event_date=DAY,
                sequence=2,
                amount=D("10"),
                fees=D("1"),
                quantity=D("1"),
                unit_price=D("10"),
                security_id="sec_fixture_primary",
                security_ticker="TSTF",
                exchange_mic="XNYS",
                reference_retrieved_at=REFERENCE.retrieved_at,
            )
            before = list(old_apps.get_model("ledger", "Entry").objects.values())
        finally:
            MigrationExecutor(connection).migrate(new_target)
        after = list(Entry.objects.values())
        self.assertEqual([{key: row[key] for key in before[0]} for row in after], before)
        self.assertTrue(all(row["split_new"] is None and row["split_old"] is None for row in after))
        result = analyze([row.as_input() for row in Entry.objects.all()])
        self.assertEqual(result.cash, D("112.45"))
        self.assertEqual(result.open_cost_basis, D("11.00"))
        with self.assertRaises(IntegrityError), transaction.atomic():
            Entry.objects.filter(pk=old_entry.pk).update(amount=D("999"))
