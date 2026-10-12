"""Block accidental ORM/raw SQL edits; database administrators retain control."""

from django.db import migrations


def install(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("""
            CREATE FUNCTION stock_research_immutable_entry() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN
              RAISE EXCEPTION 'Ledger entries are immutable' USING ERRCODE = '23514';
            END $$;
            CREATE TRIGGER ledger_immutable BEFORE UPDATE OR DELETE ON ledger_entry
            FOR EACH ROW EXECUTE FUNCTION stock_research_immutable_entry();
        """)


def uninstall(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("""
            DROP TRIGGER ledger_immutable ON ledger_entry;
            DROP FUNCTION stock_research_immutable_entry();
        """)


class Migration(migrations.Migration):
    dependencies = [("ledger", "0001_initial")]
    operations = [migrations.RunPython(install, uninstall)]
