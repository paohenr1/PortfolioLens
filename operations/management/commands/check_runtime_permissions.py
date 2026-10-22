"""Inspect effective PostgreSQL privileges without reading or changing application data."""

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection

APPEND_ONLY = {"ledger_entry", "ledger_correction"}
REFERENCE = {"auth_group", "auth_permission", "auth_group_permissions", "django_content_type"}


class Command(BaseCommand):
    help = "Read-only check of the connected runtime role's table and sequence privileges."

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            raise CommandError("Runtime permission verification requires PostgreSQL.")
        missing = []
        models = apps.get_models(include_auto_created=True)
        tables = sorted({model._meta.db_table for model in models if model._meta.managed})
        try:
            with connection.cursor() as cursor:
                for table in tables:
                    cursor.execute("SELECT to_regclass(%s)::oid", [table])
                    oid = cursor.fetchone()[0]
                    if oid is None:
                        missing.append(f"{table}: table missing or outside search_path")
                        continue
                    privileges = ("SELECT", "INSERT", "UPDATE", "DELETE")
                    if table in APPEND_ONLY:
                        privileges = ("SELECT", "INSERT")
                    elif table in REFERENCE:
                        privileges = ("SELECT",)
                    cursor.execute(
                        "SELECT has_schema_privilege(relnamespace, 'USAGE') "
                        "FROM pg_class WHERE oid = %s",
                        [oid],
                    )
                    if not cursor.fetchone()[0]:
                        missing.append(f"{table}: schema USAGE")
                    for privilege in privileges:
                        cursor.execute("SELECT has_table_privilege(%s, %s)", [oid, privilege])
                        if not cursor.fetchone()[0]:
                            missing.append(f"{table}: {privilege}")
                    # Includes serial and identity sequences, without advancing either.
                    cursor.execute(
                        "SELECT pg_get_serial_sequence(%s, attname) "
                        "FROM pg_attribute WHERE attrelid = %s "
                        "AND attnum > 0 AND NOT attisdropped",
                        [table, oid],
                    )
                    sequences = {row[0] for row in cursor.fetchall() if row[0]}
                    for sequence in sorted(sequences):
                        cursor.execute(
                            "SELECT has_sequence_privilege(%s, 'USAGE') "
                            "OR has_sequence_privilege(%s, 'UPDATE')",
                            [sequence, sequence],
                        )
                        if not cursor.fetchone()[0]:
                            missing.append(f"{sequence}: USAGE or UPDATE (nextval)")
        except DatabaseError:
            raise CommandError(
                "Could not inspect runtime permissions; check database access."
            ) from None
        if missing:
            raise CommandError("Runtime permissions missing:\n" + "\n".join(missing))
        self.stdout.write(self.style.SUCCESS("Runtime table and sequence permissions verified."))
