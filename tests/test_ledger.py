"""Real PostgreSQL ledger behavior, private HTTP boundaries, and write races."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from ledger.domain import replay
from ledger.models import Entry
from ledger.services import PortfolioUnavailable, append_entry
from market_data.contracts import Security, SecurityResult
from market_data.errors import CredentialsMissing, ProviderRateLimited
from portfolios.services import create_portfolio
from tests.test_ledger_domain import DAY, cash, trade

D = Decimal
REFERENCE = SecurityResult(
    Security("sec_fixture_primary", "TSTF", "Fixture Research Corp", "XNYS", "USD"),
    datetime(2020, 1, 2, tzinfo=UTC),
)


@skipUnless(connection.vendor == "postgresql", "Ledger persistence requires PostgreSQL")
class LedgerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = get_user_model().objects.create_user("ledger-alice")
        cls.bob = get_user_model().objects.create_user("ledger-bob")
        cls.portfolio = create_portfolio(owner=cls.alice, name="Ledger fixture")
        cls.foreign = create_portfolio(owner=cls.bob, name="Private foreign ledger")

    def setUp(self):
        self.client.force_login(self.alice)
        self.provider = patch(
            "ledger.services.market_data.security_details", return_value=REFERENCE
        ).start()
        self.addCleanup(patch.stopall)

    def record(self, intent, key=None, portfolio=None, user=None):
        return append_entry(
            user=user or self.alice,
            portfolio_id=(portfolio or self.portfolio).pk,
            client_key=key or uuid.uuid4(),
            intent=intent,
            client_address="127.0.0.1",
        )

    def url(self, name, portfolio=None):
        return reverse(name, args=[(portfolio or self.portfolio).pk])

    def post_data(self, **data):
        return {
            "kind": "DEPOSIT",
            "currency": "USD",
            "event_date": "2020-01-02",
            "sequence": "1",
            "amount": "1000",
            "fees": "0",
            "client_key": str(uuid.uuid4()),
            **data,
        }

    def test_cash_entries_are_persisted_without_provider_calls(self):
        self.record(cash())
        self.record(cash("WITHDRAWAL", "10", 2))
        self.record(cash("FEE", "1", 3))
        self.provider.assert_not_called()
        self.assertEqual(
            replay([entry.as_input() for entry in Entry.objects.all()]).cash, D("989.00")
        )

    def test_trade_preserves_exact_prices_reference_and_raw_execution_basis(self):
        self.record(cash())
        entry = self.record(trade(quantity="0.5", price="1.01", fees="0.02"))
        entry.refresh_from_db()
        self.assertEqual(entry.quantity, D("0.500000"))
        self.assertEqual(entry.unit_price, D("1.010000"))
        self.assertEqual(entry.amount, D("0.51"))
        self.assertEqual(entry.cash_delta, D("-0.53"))
        self.assertEqual(entry.security_ticker, "TSTF")
        self.assertEqual(entry.exchange_mic, "XNYS")
        self.assertEqual(entry.reference_retrieved_at, REFERENCE.retrieved_at)
        self.provider.assert_called_once_with("sec_fixture_primary", "127.0.0.1")

    def test_exact_retry_returns_same_entry_without_provider_or_second_insert(self):
        self.record(cash())
        key = uuid.uuid4()
        first = self.record(trade(), key)
        self.provider.reset_mock()
        second = self.record(trade(), key)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Entry.objects.count(), 2)
        self.provider.assert_not_called()

    def test_retry_with_changed_details_is_rejected(self):
        key = uuid.uuid4()
        self.record(cash(), key)
        with self.assertRaisesMessage(ValidationError, "different details"):
            self.record(cash(amount="2000"), key)
        self.assertEqual(Entry.objects.count(), 1)

    def test_submission_keys_are_scoped_to_portfolio(self):
        key = uuid.uuid4()
        first = self.record(cash(), key)
        second = self.record(cash(), key, self.foreign, self.bob)
        self.assertNotEqual(first.pk, second.pk)

    def test_insufficient_cash_and_shares_reject_before_provider_lookup(self):
        with self.assertRaisesMessage(ValidationError, "cash negative"):
            self.record(trade())
        self.record(cash())
        with self.assertRaisesMessage(ValidationError, "short position"):
            self.record(trade("SELL"))
        self.provider.assert_not_called()
        self.assertEqual(Entry.objects.count(), 1)

    def test_backdated_entry_that_invalidates_later_cash_is_rejected(self):
        self.record(cash(event_date=date(2020, 1, 1)))
        self.record(cash("WITHDRAWAL", "900", 1, date(2020, 1, 3)))
        with self.assertRaisesMessage(ValidationError, "cash negative"):
            self.record(cash("WITHDRAWAL", "200", 1, date(2020, 1, 2)))
        self.assertEqual(Entry.objects.count(), 2)

    def test_distinct_order_required_and_backdated_valid_insert_replays(self):
        self.record(cash(event_date=date(2020, 1, 3)))
        with self.assertRaisesMessage(ValidationError, "already used"):
            self.record(cash(event_date=date(2020, 1, 3)))
        self.record(cash(amount="10", event_date=date(2020, 1, 1)))
        self.assertEqual(
            list(Entry.objects.values_list("event_date", flat=True)),
            [date(2020, 1, 1), date(2020, 1, 3)],
        )

    def test_reference_failure_currency_venue_or_missing_ticker_cannot_write(self):
        self.record(cash())
        for security in (
            replace(REFERENCE.security, currency="CAD"),
            replace(REFERENCE.security, currency=None),
            replace(REFERENCE.security, exchange_mic="XLON"),
            replace(REFERENCE.security, ticker=None),
        ):
            with self.subTest(security=security):
                self.provider.return_value = replace(REFERENCE, security=security)
                with self.assertRaises(ValidationError):
                    self.record(trade())
        self.assertEqual(Entry.objects.count(), 1)

    def test_provider_identity_mismatch_is_rejected(self):
        from market_data.errors import InvalidResponse

        self.record(cash())
        self.provider.return_value = replace(
            REFERENCE, security=replace(REFERENCE.security, id="wrong")
        )
        with self.assertRaises(InvalidResponse):
            self.record(trade())
        self.assertEqual(Entry.objects.count(), 1)

    def test_reference_venue_change_requires_reconciliation(self):
        self.record(cash())
        self.record(trade())
        self.provider.return_value = replace(
            REFERENCE, security=replace(REFERENCE.security, exchange_mic="XNAS")
        )
        with self.assertRaisesMessage(ValidationError, "venue changed"):
            self.record(trade(sequence=3))
        self.assertEqual(Entry.objects.count(), 2)

    def test_foreign_owner_cannot_record_or_read_and_makes_no_provider_call(self):
        for name in ("ledger_history", "ledger_create"):
            response = self.client.get(self.url(name, self.foreign))
            self.assertEqual(response.status_code, 404)
            self.assertIn("no-store", response.headers["Cache-Control"])
            self.assertNotContains(response, "Private foreign ledger", status_code=404)
        self.assertEqual(
            self.client.post(self.url("ledger_create", self.foreign), self.post_data()).status_code,
            404,
        )
        with self.assertRaises(PortfolioUnavailable):
            self.record(cash(), portfolio=self.foreign)
        self.provider.assert_not_called()
        self.assertEqual(Entry.objects.count(), 0)

    def test_signed_out_routes_redirect_without_writes(self):
        self.client.logout()
        for name in ("ledger_history", "ledger_create"):
            url = self.url(name)
            self.assertRedirects(self.client.get(url), f"/sign-in/?next={url}")
        self.assertEqual(Entry.objects.count(), 0)

    def test_csrf_enforcement_and_valid_form_write(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.alice)
        url = self.url("ledger_create")
        self.assertEqual(client.post(url, self.post_data()).status_code, 403)
        self.assertEqual(Entry.objects.count(), 0)
        client.get(url)
        response = client.post(
            url, self.post_data(csrfmiddlewaretoken=client.cookies["csrftoken"].value)
        )
        self.assertRedirects(response, self.url("ledger_history"))
        self.assertEqual(Entry.objects.count(), 1)
        self.assertEqual(response.wsgi_request.sensitive_post_parameters, "__ALL__")

    def test_invalid_forms_do_not_write_or_spend_provider_quota(self):
        for values in (
            {"kind": "SPLIT"},
            {"event_date": "2099-01-01"},
            {"amount": "-1"},
            {"amount": "NaN"},
            {"amount": "1.001"},
            {"client_key": "bad"},
            {
                "currency": "CAD",
                "kind": "BUY",
                "amount": "",
                "security_id": "bad.id",
                "quantity": "1",
                "unit_price": "10",
            },
        ):
            response = self.client.post(self.url("ledger_create"), self.post_data(**values))
            self.assertTrue(response.context["form"].errors)
            self.assertEqual(Entry.objects.count(), 0)
        self.provider.assert_not_called()

    def test_unknown_fields_cannot_change_owner_or_instrument_snapshot(self):
        response = self.client.post(
            self.url("ledger_create"),
            self.post_data(
                portfolio=self.foreign.pk,
                owner=self.bob.pk,
                security_ticker="FORGED",
            ),
        )
        self.assertEqual(response.status_code, 302)
        entry = Entry.objects.get()
        self.assertEqual(entry.portfolio, self.portfolio)
        self.assertEqual(entry.currency, "USD")
        self.assertEqual(entry.security_ticker, "")

    def test_provider_error_safe_status_and_retry_after_preserve_no_write(self):
        self.record(cash())
        for error, status in ((CredentialsMissing(), 503), (ProviderRateLimited(30), 429)):
            self.provider.side_effect = error
            response = self.client.post(
                self.url("ledger_create"),
                self.post_data(
                    kind="BUY",
                    amount="",
                    sequence=2,
                    security_id="sec_fixture_primary",
                    quantity="1",
                    unit_price="10",
                ),
            )
            self.assertEqual(response.status_code, status)
            self.assertContains(response, "No transaction was recorded", status_code=status)
            self.assertIn("no-store", response.headers["Cache-Control"])
            if status == 429:
                self.assertEqual(response.headers["Retry-After"], "30")
            self.assertEqual(Entry.objects.count(), 1)

    def test_history_shows_derived_cash_source_units_and_no_market_value(self):
        self.record(cash())
        self.record(trade())
        response = self.client.get(self.url("ledger_history"))
        self.assertContains(response, "Recorded cash: 749.00 USD")
        self.assertContains(response, "TSTF")
        self.assertContains(response, "USD/share")
        self.assertContains(response, "not a verified brokerage balance or investment return")
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_ledger_gets_and_history_post_do_not_write(self):
        self.assertEqual(self.client.get(self.url("ledger_create")).status_code, 200)
        self.assertEqual(self.client.get(self.url("ledger_history")).status_code, 200)
        self.assertEqual(
            self.client.post(self.url("ledger_history"), self.post_data()).status_code, 405
        )
        self.assertEqual(Entry.objects.count(), 0)

    def test_append_only_model_queryset_and_raw_sql_protection(self):
        entry = self.record(cash())
        entry.amount = D("10")
        with self.assertRaises(ValidationError):
            entry.save()
        with self.assertRaises(ValidationError):
            entry.delete()
        for action in (
            lambda: Entry.objects.filter(pk=entry.pk).update(amount=D("10")),
            lambda: Entry.objects.filter(pk=entry.pk).delete(),
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                action()
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM ledger_entry WHERE id=%s", [entry.pk])
        entry.refresh_from_db()
        self.assertEqual(entry.amount, D("1000"))

    def test_database_constraints_cover_shape_cash_order_currency_and_idempotency(self):
        original = self.record(cash())
        base = {
            "portfolio": self.portfolio,
            "client_key": uuid.uuid4(),
            "kind": "DEPOSIT",
            "event_date": DAY,
            "sequence": 2,
            "amount": D("1"),
        }
        for changes in (
            {"currency": "CAD"},
            {"kind": "UNKNOWN"},
            {"amount": D("0")},
            {"fees": D("1")},
            {"quantity": D("1")},
            {"sequence": 0},
            {"sequence": 1},
            {"client_key": original.client_key},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    Entry.objects.create(**{**base, **changes})

    def test_database_checks_trade_amount_matches_exact_rounding(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Entry.objects.create(
                portfolio=self.portfolio,
                client_key=uuid.uuid4(),
                kind="BUY",
                event_date=DAY,
                sequence=1,
                amount=D("999"),
                quantity=D("1"),
                unit_price=D("10"),
                security_id="sec_fixture_primary",
                security_ticker="TSTF",
                exchange_mic="XNYS",
                reference_retrieved_at=REFERENCE.retrieved_at,
            )

    def test_portfolio_deletion_is_protected_when_ledger_exists(self):
        self.record(cash())
        with self.assertRaises(ProtectedError):
            self.portfolio.delete()

    def test_entry_allowance_blocks_new_entries_but_allows_exact_retry(self):
        key = uuid.uuid4()
        entry = self.record(cash(), key)
        Entry.objects.bulk_create(
            [
                Entry(
                    portfolio=self.portfolio,
                    client_key=uuid.uuid4(),
                    kind="DEPOSIT",
                    event_date=DAY,
                    sequence=n,
                    amount=D("1"),
                )
                for n in range(2, 1001)
            ]
        )
        with self.assertRaisesMessage(ValidationError, "development limit"):
            self.record(cash(sequence=1001))
        self.assertEqual(self.record(cash(), key).pk, entry.pk)
        self.assertEqual(Entry.objects.count(), 1000)

    def test_page_cash_uses_all_history_and_not_only_visible_rows(self):
        Entry.objects.bulk_create(
            [
                Entry(
                    portfolio=self.portfolio,
                    client_key=uuid.uuid4(),
                    kind="DEPOSIT",
                    event_date=DAY,
                    sequence=n,
                    amount=D("1"),
                )
                for n in range(1, 27)
            ]
        )
        response = self.client.get(self.url("ledger_history"), {"page": 2})
        self.assertEqual(response.context["cash"], D("26.00"))
        self.assertEqual(len(response.context["page"].object_list), 1)

    def test_toronto_midnight_and_unsupported_currency_validate_before_lookup(self):
        from ledger.forms import ledger_today

        with patch("ledger.forms.timezone.now", return_value=datetime(2026, 10, 10, 1, tzinfo=UTC)):
            self.assertEqual(ledger_today(), date(2026, 10, 9))
        # Freeze the ledger date only: changing Django's global clock also changes
        # session expiry and can log the client out during the following request.
        with patch("ledger.forms.ledger_today", return_value=date(2026, 10, 9)):
            response = self.client.post(
                self.url("ledger_create"), self.post_data(event_date="2026-10-10")
            )
            self.assertTrue(response.context["form"].errors)
        response = self.client.post(self.url("ledger_create"), self.post_data(currency="CAD"))
        self.assertTrue(response.context["form"].errors)
        with self.assertRaisesMessage(ValidationError, "Only USD"):
            self.record(replace(cash(), currency="CAD"))
        self.provider.assert_not_called()
        self.assertEqual(Entry.objects.count(), 0)


@skipUnless(connection.vendor == "postgresql", "Ledger races require PostgreSQL")
class LedgerConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("ledger-race")
        self.portfolio = create_portfolio(owner=self.owner, name="Concurrent ledger")
        self.provider = patch(
            "ledger.services.market_data.security_details", return_value=REFERENCE
        ).start()
        self.addCleanup(patch.stopall)
        self.record(cash())

    def record(self, intent, key=None):
        return append_entry(
            user=self.owner,
            portfolio_id=self.portfolio.pk,
            client_key=key or uuid.uuid4(),
            intent=intent,
            client_address="127.0.0.1",
        )

    def race(self, requests):
        barrier = Barrier(2)

        def submit(request):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                try:
                    return "created", self.record(*request).pk
                except ValidationError:
                    return "rejected", None
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            return list(executor.map(submit, requests))

    def test_concurrent_sells_cannot_oversell(self):
        self.record(trade(quantity="10", fees="0"))
        results = self.race(
            ((trade("SELL", "7", "25", "0", 3), None), (trade("SELL", "7", "25", "0", 4), None))
        )
        self.assertCountEqual([result[0] for result in results], ["created", "rejected"])
        self.assertEqual(
            replay([entry.as_input() for entry in Entry.objects.all()]).quantities[
                "sec_fixture_primary"
            ],
            D("3"),
        )

    def test_concurrent_same_submission_returns_one_entry(self):
        key = uuid.uuid4()
        results = self.race(
            ((cash(amount="10", sequence=2), key), (cash(amount="10", sequence=2), key))
        )
        self.assertEqual(results[0][1], results[1][1])
        self.assertEqual(Entry.objects.count(), 2)

    def test_concurrent_withdrawals_cannot_overdraw_cash(self):
        results = self.race(
            ((cash("WITHDRAWAL", "700", 2), None), (cash("WITHDRAWAL", "700", 3), None))
        )
        self.assertCountEqual([result[0] for result in results], ["created", "rejected"])
        self.assertEqual(
            replay([entry.as_input() for entry in Entry.objects.all()]).cash, D("300.00")
        )
