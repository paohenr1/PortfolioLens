"""Protect correction links, replacement completeness and effective date/order."""

from django.db import migrations


def install(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
        CREATE TRIGGER correction_immutable BEFORE UPDATE OR DELETE ON ledger_correction
        FOR EACH ROW EXECUTE FUNCTION stock_research_immutable_entry();

        CREATE FUNCTION stock_research_correction_links() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
          PERFORM id FROM portfolios_portfolio WHERE id=NEW.portfolio_id FOR NO KEY UPDATE;
          IF NOT EXISTS (SELECT 1 FROM ledger_entry
              WHERE id=NEW.target_id AND portfolio_id=NEW.portfolio_id)
            OR (NEW.replacement_id IS NOT NULL AND NOT EXISTS (
              SELECT 1 FROM ledger_entry WHERE id=NEW.replacement_id
                AND portfolio_id=NEW.portfolio_id AND is_replacement))
            OR EXISTS (SELECT 1 FROM ledger_correction WHERE target_id=NEW.replacement_id)
          THEN
            RAISE EXCEPTION 'Invalid correction links' USING ERRCODE='23514';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER correction_links BEFORE INSERT ON ledger_correction
        FOR EACH ROW EXECUTE FUNCTION stock_research_correction_links();

        CREATE FUNCTION stock_research_effective_order() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
          -- Serialize direct inserts with a lock compatible with FK KEY SHARE checks.
          PERFORM id FROM portfolios_portfolio WHERE id=NEW.portfolio_id FOR NO KEY UPDATE;
          IF NEW.is_replacement AND NOT EXISTS (
              SELECT 1 FROM ledger_correction WHERE replacement_id=NEW.id)
          THEN
            RAISE EXCEPTION 'Replacement requires a correction' USING ERRCODE='23514';
          END IF;
          IF (SELECT count(*) FROM ledger_entry e
              WHERE e.portfolio_id=NEW.portfolio_id
                AND e.event_date=NEW.event_date AND e.sequence=NEW.sequence
                AND NOT EXISTS (SELECT 1 FROM ledger_correction c WHERE c.target_id=e.id)) > 1
          THEN
            RAISE EXCEPTION 'Effective journal order must be unique'
              USING ERRCODE='23514', CONSTRAINT='ledger_effective_order_unique';
          END IF;
          RETURN NEW;
        END $$;
        -- Replacement insertion and the audit link are allowed to complete
        -- together; constraints check the final transaction interpretation.
        CREATE CONSTRAINT TRIGGER ledger_effective_order AFTER INSERT ON ledger_entry
        DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
        EXECUTE FUNCTION stock_research_effective_order();
    """)


def uninstall(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("""
            DROP TRIGGER ledger_effective_order ON ledger_entry;
            DROP FUNCTION stock_research_effective_order();
            DROP TRIGGER correction_links ON ledger_correction;
            DROP FUNCTION stock_research_correction_links();
            DROP TRIGGER correction_immutable ON ledger_correction;
        """)


class Migration(migrations.Migration):
    dependencies = [("ledger", "0004_corrections")]
    operations = [migrations.RunPython(install, uninstall)]
