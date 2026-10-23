"""Automatic date-local ordering, idempotency and concurrency on real PostgreSQL."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from ledger.models import Entry
from ledger.services import append_entry
from portfolios.services import create_portfolio
from tests.test_ledger_domain import DAY, cash


@skipUnless(connection.vendor == "postgresql", "Automatic order requires PostgreSQL")
class AutomaticOrderTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("automatic-owner")
        self.portfolio = create_portfolio(owner=self.user, name="Automatic example")
        self.client.force_login(self.user)

    def append(self, event=None, key=None):
        return append_entry(
            user=self.user,
            portfolio_id=self.portfolio.pk,
            client_key=key or uuid.uuid4(),
            intent=event or cash(amount="10"),
            client_address="127.0.0.1",
            auto_sequence=True,
        )

    def test_order_increases_and_retry_reuses_original_after_other_entries(self):
        key = uuid.uuid4()
        first = self.append(key=key)
        second = self.append()
        self.assertEqual((first.sequence, second.sequence), (1, 2))
        self.assertEqual(self.append(key=key).pk, first.pk)
        self.assertEqual(Entry.objects.count(), 2)
        with self.assertRaises(ValidationError):
            self.append(cash(amount="20"), key)

    def test_backdating_still_validates_later_cash_and_existing_records_are_not_reordered(self):
        first = self.append(cash(amount="10", sequence=55))
        self.assertEqual(first.sequence, 1)
        self.append(cash("WITHDRAWAL", "10", event_date=DAY + timedelta(days=1)))
        with self.assertRaises(ValidationError):
            self.append(cash("WITHDRAWAL", "1"))
        first.refresh_from_db()
        self.assertEqual(first.sequence, 1)

    def test_new_entry_has_two_separate_modes_and_no_manual_order(self):
        url = reverse("ledger_create", args=[self.portfolio.pk])
        for mode, kinds in (("trade", ["BUY", "SELL"]), ("cash", ["DEPOSIT", "WITHDRAWAL"])):
            response = self.client.get(url, {"mode": mode})
            self.assertEqual([x[0] for x in response.context["form"].fields["kind"].choices], kinds)
            self.assertNotContains(response, "Same-day order")
            self.assertNotContains(response, 'name="sequence"')
            for kind in ("FEE", "SPLIT", "DIVIDEND"):
                self.assertNotContains(response, f'<option value="{kind}"')
        data = {
            "kind": "DEPOSIT",
            "currency": "USD",
            "amount": "10",
            "event_date": DAY,
            "client_key": uuid.uuid4(),
        }
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(Entry.objects.count(), 1)
        self.assertEqual(Entry.objects.get().sequence, 1)


@skipUnless(connection.vendor == "postgresql", "Ordering locks require PostgreSQL")
class AutomaticOrderConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("automatic-concurrency")
        self.portfolio = create_portfolio(owner=self.user, name="Concurrent example")

    def race(self, keys):
        barrier = Barrier(2)

        def save(key):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                return append_entry(
                    user=self.user,
                    portfolio_id=self.portfolio.pk,
                    client_key=key,
                    intent=cash(amount="10"),
                    client_address="127.0.0.1",
                    auto_sequence=True,
                ).pk
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            return list(executor.map(save, keys))

    def test_concurrent_entries_receive_distinct_positions(self):
        results = self.race([uuid.uuid4(), uuid.uuid4()])
        self.assertEqual(len(set(results)), 2)
        self.assertEqual(sorted(Entry.objects.values_list("sequence", flat=True)), [1, 2])

    def test_concurrent_retries_create_one_transaction(self):
        key = uuid.uuid4()
        results = self.race([key, key])
        self.assertEqual(results[0], results[1])
        self.assertEqual(Entry.objects.count(), 1)
