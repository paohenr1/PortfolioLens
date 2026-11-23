"""Map existing stored instrument IDs without changing journal or holdings rows."""

import uuid
from itertools import islice

from django.db import migrations


def seed_intrinio_instruments(apps, schema_editor):
    database = schema_editor.connection.alias
    sources = [
        apps.get_model(app_label, model).objects.using(database)
        .exclude(security_id="").order_by().values_list("security_id", flat=True)
        for app_label, model in (
            ("ledger", "Entry"),
            ("watchlists", "WatchlistItem"),
            ("portfolios", "SnapshotHolding"),
        )
    ]
    identifiers = sources[0].union(*sources[1:]).iterator(chunk_size=500)
    instruments = apps.get_model("market_data", "InstrumentIdentity").objects.using(database)
    mappings = apps.get_model("market_data", "InstrumentProviderID").objects.using(database)
    while batch := list(islice(identifiers, 500)):
        existing = set(
            mappings.filter(provider="intrinio", external_id__in=batch)
            .values_list("external_id", flat=True)
        )
        pairs = [(external_id, uuid.uuid4()) for external_id in batch if external_id not in existing]
        instruments.bulk_create([instruments.model(id=local_id) for _, local_id in pairs])
        mappings.bulk_create([
            mappings.model(provider="intrinio", external_id=external_id, instrument_id=local_id)
            for external_id, local_id in pairs
        ])


class Migration(migrations.Migration):
    dependencies = [
        ("market_data", "0001_initial"),
        ("ledger", "0001_initial"),
        ("watchlists", "0001_initial"),
        ("portfolios", "0002_holdingssnapshot_snapshotholding_snapshotsubmission_and_more"),
    ]
    operations = [
        migrations.RunPython(seed_intrinio_instruments, migrations.RunPython.noop),
    ]
