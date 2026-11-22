"""Verify precise listing and issuer mappings on PostgreSQL."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from importlib import import_module
from io import StringIO
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase

from ledger.services import append_entry
from market_data.identities import register_intrinio_instrument
from market_data.models import CompanyIdentity, InstrumentIdentity, InstrumentProviderID
from portfolios.services import create_portfolio
from tests.test_ledger import REFERENCE
from tests.test_ledger_domain import cash, trade


@skipUnless(connection.vendor == "postgresql", "Identity integration requires PostgreSQL")
class MarketIdentityTests(TestCase):
    def test_two_listings_share_one_issuer_and_can_map_to_other_providers(self):
        first = register_intrinio_instrument("sec_class_a")
        second = register_intrinio_instrument("sec_class_b", "com_alphabet")
        self.assertEqual(register_intrinio_instrument("sec_class_a", "com_alphabet"), first)
        self.assertNotEqual(first, second)
        self.assertEqual(
            set(InstrumentIdentity.objects.values_list("company_id", flat=True)),
            {CompanyIdentity.objects.get().pk},
        )
        InstrumentProviderID.objects.create(
            provider="another-provider", external_id="alphabet-class-a", instrument_id=first
        )
        self.assertEqual(
            InstrumentProviderID.objects.get(
                provider="another-provider", external_id="alphabet-class-a"
            ).instrument_id,
            first,
        )

    def test_conflicting_issuer_never_reassigns_saved_instrument(self):
        instrument = register_intrinio_instrument("sec_fixture", "com_original")
        issuer = InstrumentIdentity.objects.get(pk=instrument).company_id
        with self.assertLogs("research", level="WARNING"):
            self.assertEqual(
                register_intrinio_instrument("sec_fixture", "com_conflict"), instrument
            )
        self.assertEqual(InstrumentIdentity.objects.get(pk=instrument).company_id, issuer)

    def test_trade_populates_registry_and_seed_recovers_historical_instrument(self):
        user = get_user_model().objects.create_user("market-identity-owner")
        portfolio = create_portfolio(owner=user, name="Identity test")
        reference = replace(
            REFERENCE, security=replace(REFERENCE.security, company_id="com_fixture")
        )
        with patch("ledger.services.market_data.security_details", return_value=reference):
            for intent in (cash(), trade()):
                entry = append_entry(
                    user=user,
                    portfolio_id=portfolio.pk,
                    client_key=uuid.uuid4(),
                    intent=intent,
                    client_address="127.0.0.1",
                )
        existing = InstrumentProviderID.objects.get(
            provider="intrinio", external_id=entry.security_id
        )
        self.assertIsNotNone(existing.instrument.company_id)
        existing.delete()
        migration = import_module("market_data.migrations.0002_seed_intrinio_instruments")
        for _ in range(2):
            migration.seed_intrinio_instruments(apps, connection.schema_editor())
        entry.refresh_from_db()
        self.assertEqual(entry.security_id, reference.security.id)
        mapping = InstrumentProviderID.objects.get(
            provider="intrinio", external_id=entry.security_id
        )
        self.assertIsNone(mapping.instrument.company_id)
        output = StringIO()
        with patch(
            "market_data.management.commands.register_intrinio_identity.security_details",
            return_value=reference,
        ):
            call_command("register_intrinio_identity", entry.security_id, stdout=output)
        self.assertEqual(output.getvalue().strip(), str(mapping.instrument_id))
        self.assertIsNotNone(InstrumentIdentity.objects.get(pk=mapping.instrument_id).company_id)


@skipUnless(connection.vendor == "postgresql", "Identity races require PostgreSQL")
class MarketIdentityConcurrencyTests(TransactionTestCase):
    def test_concurrent_registration_uses_one_company_and_one_instrument(self):
        barrier = Barrier(2)

        def register():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                return register_intrinio_instrument("sec_race", "com_race")
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [pool.submit(register) for _ in range(2)]
            first, second = [result.result(timeout=10) for result in results]
        self.assertEqual(first, second)
        self.assertEqual(InstrumentIdentity.objects.count(), 1)
        self.assertEqual(CompanyIdentity.objects.count(), 1)
