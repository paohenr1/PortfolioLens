# Company and instrument identities

PortfolioLens assigns local UUIDs to companies and tradable instruments. Provider
mappings use the pair of provider name and external ID. One company can be linked
to multiple instruments. Two share classes stay separate even when Intrinio
reports the same company ID. Tickers, company names and exchanges are display
metadata and are never used to infer identity.

The migration registers existing Intrinio instrument IDs from the journal,
watchlists and holdings snapshots without querying Intrinio or rewriting those
records. The stored instrument ID resolves through
`InstrumentProviderID(provider="intrinio", external_id=...)`. If the original
record lacks company information, the new instrument starts without a company.

New transactions and watchlist additions register the instrument and its company
when the verified Intrinio response supplies one. Snapshot saves register
instrument IDs from the existing verified preview. A later observation can fill
a missing company link. Conflicting metadata leaves the established link intact
for manual reconciliation.

To verify or enrich an individual listing using the configured Intrinio account:

```sh
uv run --frozen python manage.py register_intrinio_identity SECURITY_ID
```

This command makes one reference request through the existing request budget and
prints the local instrument UUID. It does not change user records.

To add a provider later, review the exact listing and issuer independently before
attaching that provider's IDs to the existing local UUIDs. Each provider ID can
point to only one local identity, and each local identity has at most one ID per
provider. Existing pricing and research still use Intrinio. The registry does
not enable provider switching by itself.

Before deploying, apply the mapping migrations using the migration role and run
the [runtime permission check](render-deployment.md#runtime-role-permissions-before-deployment)
for the new tables and mapping sequences. Avoid writes from an older release
during the backfill and rollout so new records are registered by the new code.
The seeded mappings are retained when the data migration alone is reversed.
