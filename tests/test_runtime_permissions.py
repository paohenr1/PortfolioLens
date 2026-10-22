"""Real PostgreSQL ACL regressions using only the disposable test database."""

from io import StringIO
from unittest import skipUnless
from uuid import uuid4

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext


@skipUnless(connection.vendor == "postgresql", "PostgreSQL privilege checks")
class RuntimePermissionTests(TestCase):
    def setUp(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_user, usesuper FROM pg_user WHERE usename = current_user"
            )
            self.owner, superuser = cursor.fetchone()
            self.runtime = self.owner
            if superuser:
                # CI uses postgres. Revoking from a superuser cannot restrict access.
                # Role creation and grants roll back with this isolated test transaction.
                self.runtime = "permission_test_" + uuid4().hex
                role = connection.ops.quote_name(self.runtime)
                cursor.execute(f"CREATE ROLE {role} NOLOGIN NOSUPERUSER")
                cursor.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
                cursor.execute(
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role}"
                )
                cursor.execute(f"GRANT USAGE, UPDATE ON ALL SEQUENCES IN SCHEMA public TO {role}")
                cursor.execute(f"SET LOCAL ROLE {role}")

    def revoke(self, privileges, objects):
        role = connection.ops.quote_name(self.runtime)
        owner = connection.ops.quote_name(self.owner)
        with connection.cursor() as cursor:
            cursor.execute(f"SET LOCAL ROLE {owner}")
            cursor.execute(f"REVOKE {privileges} ON {objects} FROM {role}, PUBLIC")
            cursor.execute(f"SET LOCAL ROLE {role}")

    def test_success_uses_only_catalog_selects(self):
        with CaptureQueriesContext(connection) as queries:
            call_command("check_runtime_permissions", stdout=StringIO())
        self.assertTrue(queries)
        self.assertTrue(all(q["sql"].lstrip().startswith("SELECT ") for q in queries))

    def test_missing_table_permissions_are_reported(self):
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            with self.subTest(privilege=privilege), transaction.atomic():
                self.revoke(privilege, "accounts_user")
                with self.assertRaisesMessage(CommandError, f"accounts_user: {privilege}"):
                    call_command("check_runtime_permissions", stdout=StringIO())
                transaction.set_rollback(True)

    def test_missing_sequence_permission_is_reported_without_advancing_sequence(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_get_serial_sequence('accounts_user', 'id')")
                sequence = cursor.fetchone()[0]
            self.revoke("USAGE, UPDATE", f"SEQUENCE {sequence}")
            with self.assertRaisesMessage(CommandError, f"{sequence}: USAGE or UPDATE"):
                call_command("check_runtime_permissions", stdout=StringIO())
            transaction.set_rollback(True)

    def test_sequence_update_alone_allows_nextval(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_get_serial_sequence('accounts_user', 'id')")
                sequence = cursor.fetchone()[0]
            self.revoke("USAGE", f"SEQUENCE {sequence}")
            call_command("check_runtime_permissions", stdout=StringIO())
            transaction.set_rollback(True)

    def test_immutable_journal_does_not_require_mutation_grants(self):
        with transaction.atomic():
            self.revoke("UPDATE, DELETE", "ledger_entry, ledger_correction")
            call_command("check_runtime_permissions", stdout=StringIO())
            transaction.set_rollback(True)
