"""Real PostgreSQL ACL regressions using only the disposable test database."""

from io import StringIO
from unittest import skipUnless

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext


@skipUnless(connection.vendor == "postgresql", "PostgreSQL privilege checks")
class RuntimePermissionTests(TestCase):
    def test_success_uses_only_catalog_selects(self):
        with CaptureQueriesContext(connection) as queries:
            call_command("check_runtime_permissions", stdout=StringIO())
        self.assertTrue(queries)
        self.assertTrue(all(q["sql"].lstrip().startswith("SELECT ") for q in queries))

    def test_missing_table_permissions_are_reported(self):
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            with self.subTest(privilege=privilege), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(f"REVOKE {privilege} ON accounts_user FROM CURRENT_USER, PUBLIC")
                with self.assertRaisesMessage(CommandError, f"accounts_user: {privilege}"):
                    call_command("check_runtime_permissions", stdout=StringIO())
                transaction.set_rollback(True)

    def test_missing_sequence_permission_is_reported_without_advancing_sequence(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_get_serial_sequence('accounts_user', 'id')")
                sequence = cursor.fetchone()[0]
                cursor.execute(
                    f"REVOKE USAGE, UPDATE ON SEQUENCE {sequence} FROM CURRENT_USER, PUBLIC"
                )
            with self.assertRaisesMessage(CommandError, f"{sequence}: USAGE or UPDATE"):
                call_command("check_runtime_permissions", stdout=StringIO())
            transaction.set_rollback(True)

    def test_sequence_update_alone_allows_nextval(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_get_serial_sequence('accounts_user', 'id')")
                sequence = cursor.fetchone()[0]
                cursor.execute(f"REVOKE USAGE ON SEQUENCE {sequence} FROM CURRENT_USER, PUBLIC")
            call_command("check_runtime_permissions", stdout=StringIO())
            transaction.set_rollback(True)

    def test_immutable_journal_does_not_require_mutation_grants(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "REVOKE UPDATE, DELETE ON ledger_entry, ledger_correction "
                    "FROM CURRENT_USER, PUBLIC"
                )
            call_command("check_runtime_permissions", stdout=StringIO())
            transaction.set_rollback(True)
