"""Private, read-only FIFO pages on actual PostgreSQL journal snapshots."""

import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.urls import reverse

from ledger.analytics import positions_snapshot
from ledger.domain import LedgerRuleError
from ledger.models import Entry
from ledger.services import append_entry
from market_data.errors import CredentialsMissing
from portfolios.services import create_portfolio
from tests.test_ledger import REFERENCE
from tests.test_ledger_domain import DAY, cash, trade

D = Decimal


@skipUnless(connection.vendor == "postgresql", "Position snapshots require PostgreSQL")
class PositionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = get_user_model().objects.create_user("positions-alice")
        cls.bob = get_user_model().objects.create_user("positions-bob")
        cls.portfolio = create_portfolio(owner=cls.alice, name="FIFO fixture")
        cls.foreign = create_portfolio(owner=cls.bob, name="Foreign position secret")

    def setUp(self):
        self.client.force_login(self.alice)
        self.provider = patch(
            "ledger.services.market_data.security_details", return_value=REFERENCE
        ).start()
        self.addCleanup(patch.stopall)

    def record(self, intent):
        return append_entry(
            user=self.alice,
            portfolio_id=self.portfolio.pk,
            client_key=uuid.uuid4(),
            intent=intent,
            client_address="127.0.0.1",
        )

    def url(self, portfolio=None):
        return reverse("portfolio_positions", args=[(portfolio or self.portfolio).pk])

    def history(self):
        self.record(cash())
        self.record(trade())
        self.record(trade("SELL", "4", "30", "2", 3))
        self.record(cash("WITHDRAWAL", "100", 4))
        self.record(cash("FEE", "3", 5))
        self.provider.reset_mock()

    def test_journal_snapshot_reconciles_exact_fifo_totals_without_writes_or_requests(self):
        self.history()
        before = list(Entry.objects.values())
        with self.assertNumQueries(2):
            portfolio, result, labels = positions_snapshot(self.alice, self.portfolio.pk)
        self.assertEqual(portfolio.pk, self.portfolio.pk)
        self.assertEqual(result.cash, D("764.00"))
        self.assertEqual(result.realized_gain, D("17.60"))
        self.assertEqual(result.open_cost_basis, D("150.60"))
        self.assertEqual(labels["sec_fixture_primary"].security_ticker, "TSTF")
        self.assertEqual(list(Entry.objects.values()), before)
        self.provider.assert_not_called()

    def test_page_displays_method_units_lot_provenance_and_pending_metrics(self):
        self.history()
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        for text in (
            "First in, first out",
            "17.60",
            "150.60",
            "100.40",
            "118.00",
            "764.00",
            "FIFO cost (USD)",
            "6.000000",
            "not a tax report",
            "Journal shares including recorded splits",
            "Contributions are not gains",
            "order 2",
        ):
            self.assertContains(response, text)
        self.assertContains(response, "Money-weighted returns remain unavailable")
        self.assertEqual(response.context["analysis"].standalone_fees, D("3.00"))
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.provider.assert_not_called()

    def test_signed_out_inactive_and_foreign_users_cannot_read_the_snapshot(self):
        self.history()
        foreign = self.client.get(self.url(self.foreign), {"owner": self.bob.pk})
        missing = self.client.get(reverse("portfolio_positions", args=[uuid.uuid4()]))
        self.assertEqual((foreign.status_code, missing.status_code), (404, 404))
        # The sign-out form's CSRF mask changes per render. Both paths must use
        # the same generic error template and expose no portfolio context.
        self.assertTemplateUsed(foreign, "portfolios/not_found.html")
        self.assertTemplateUsed(missing, "portfolios/not_found.html")
        self.assertIsNone(foreign.context.get("portfolio"))
        self.assertIsNone(missing.context.get("portfolio"))
        self.assertNotContains(foreign, "Foreign position secret", status_code=404)
        self.assertIn("no-store", foreign.headers["Cache-Control"])
        self.client.logout()
        self.assertRedirects(
            self.client.get(self.url()),
            "/sign-in/?next=" + self.url(),
            fetch_redirect_response=False,
        )
        self.alice.is_active = False
        self.alice.save(update_fields=["is_active"])
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(self.url()).status_code, 302)
        self.provider.assert_not_called()

    def test_forged_owner_and_portfolio_query_parameters_cannot_change_result(self):
        self.history()
        response = self.client.get(
            self.url(), {"owner_id": self.bob.pk, "portfolio_id": self.foreign.pk}
        )
        self.assertContains(response, "FIFO fixture")
        self.assertNotContains(response, "Foreign position secret")
        self.assertEqual(response.context["analysis"].realized_gain, D("17.60"))

    def test_get_only_and_private_routing_errors_do_not_write(self):
        self.history()
        before = Entry.objects.count()
        self.assertEqual(self.client.post(self.url(), {}).status_code, 405)
        response = self.client.get("/portfolios/not-a-uuid/positions/")
        self.assertEqual(response.status_code, 404)
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(Entry.objects.count(), before)
        self.provider.assert_not_called()

    def test_empty_journal_has_computed_zeros_and_explicit_empty_sections(self):
        response = self.client.get(self.url())
        self.assertEqual(response.context["analysis"].realized_gain, D("0.00"))
        self.assertEqual(response.context["analysis"].open_cost_basis, D("0.00"))
        self.assertContains(response, "No open positions")
        self.assertContains(response, "No sales recorded")
        self.provider.assert_not_called()

    def test_complete_close_retains_sale_and_negative_gain_without_an_open_row(self):
        self.record(cash())
        self.record(trade(quantity="1", price="25", fees="1"))
        self.record(trade("SELL", "1", "20", "2", 3))
        self.provider.reset_mock()
        response = self.client.get(self.url())
        self.assertContains(response, "No open positions")
        self.assertContains(response, "-8.00")
        self.assertEqual(len(response.context["sales"].object_list), 1)
        self.provider.assert_not_called()

    def test_missing_provider_access_does_not_prevent_existing_journal_calculations(self):
        self.history()
        self.provider.side_effect = CredentialsMissing()
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["analysis"].realized_gain, D("17.60"))
        self.provider.assert_not_called()

    def test_latest_reference_label_handles_ticker_changes_and_is_html_escaped(self):
        self.history()
        changed = replace(
            REFERENCE,
            security=replace(REFERENCE.security, ticker="<NEW>"),
            retrieved_at=REFERENCE.retrieved_at + timedelta(days=1),
        )
        self.provider.return_value = changed
        self.record(trade(quantity="1", price="10", fees="0", sequence=6))
        self.provider.reset_mock()
        response = self.client.get(self.url())
        self.assertContains(response, "&lt;NEW&gt;")
        self.assertNotContains(response, "<NEW>")
        self.assertEqual(len(response.context["positions"].object_list), 1)
        self.assertEqual(response.context["analysis"].positions[0].quantity, D("7.000000"))
        self.provider.assert_not_called()

    def test_both_tables_paginate_independently_while_totals_include_every_entry(self):
        self.record(cash(amount="10000"))
        entries = []
        for n in range(26):
            for kind, quantity, price, sequence in (
                ("BUY", "2", "10", 2 * n + 2),
                ("SELL", "1", "20", 2 * n + 3),
            ):
                entries.append(
                    Entry(
                        portfolio=self.portfolio,
                        client_key=uuid.uuid4(),
                        kind=kind,
                        event_date=DAY,
                        sequence=sequence,
                        security_id=f"fixture_{n}",
                        security_ticker="TSTF",
                        exchange_mic="XNYS",
                        reference_retrieved_at=datetime(2020, 1, 2, tzinfo=UTC),
                        quantity=D(quantity),
                        unit_price=D(price),
                        amount=D("20"),
                    )
                )
        Entry.objects.bulk_create(entries)
        response = self.client.get(self.url(), {"positions_page": 2, "sales_page": 2})
        self.assertEqual(len(response.context["positions"].object_list), 1)
        self.assertEqual(len(response.context["sales"].object_list), 1)
        self.assertEqual(response.context["analysis"].realized_gain, D("260.00"))
        self.assertEqual(response.context["analysis"].open_cost_basis, D("260.00"))
        self.assertContains(response, "sales_page=1&amp;positions_page=2")
        self.assertContains(response, "positions_page=1&amp;sales_page=2")
        invalid = self.client.get(self.url(), {"positions_page": "no", "sales_page": "999"})
        self.assertEqual(invalid.context["positions"].number, 1)
        self.assertEqual(invalid.context["sales"].number, 2)
        self.provider.assert_not_called()

    def test_invalid_direct_insert_fails_closed_without_displaying_made_up_totals(self):
        Entry.objects.create(
            portfolio=self.portfolio,
            client_key=uuid.uuid4(),
            kind="WITHDRAWAL",
            event_date=DAY,
            sequence=1,
            amount=D("1"),
        )
        response = self.client.get(self.url())
        self.assertContains(response, "Position calculations are unavailable", status_code=503)
        self.assertNotContains(response, "Recorded journal totals", status_code=503)
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.provider.assert_not_called()

    def test_future_direct_insert_cannot_enter_a_displayed_projection(self):
        Entry.objects.create(
            portfolio=self.portfolio,
            client_key=uuid.uuid4(),
            kind="DEPOSIT",
            event_date=date(2099, 1, 1),
            sequence=1,
            amount=D("1"),
        )
        self.assertEqual(self.client.get(self.url()).status_code, 503)
        self.provider.assert_not_called()

    def test_oversized_direct_insert_journal_is_bounded_and_unavailable(self):
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
                for n in range(1, 1002)
            ]
        )
        with self.assertRaises(LedgerRuleError), self.assertNumQueries(2):
            positions_snapshot(self.alice, self.portfolio.pk)
        self.assertEqual(self.client.get(self.url()).status_code, 503)
        self.provider.assert_not_called()
