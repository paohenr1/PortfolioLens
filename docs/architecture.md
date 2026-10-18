# Architecture

PortfolioLens is one Django application with server-rendered templates and local
CSS/JavaScript. PostgreSQL stores accounts, private portfolios, journal entries,
correction audits, holdings snapshots, watchlists and shared request counters. Intrinio supplies
market/reference data through backend HTTP requests.

## Module responsibilities

| Module | Responsibility |
| --- | --- |
| `config` | Settings, routing, middleware and runtime configuration |
| `accounts` | Django session authentication, account forms and attempt limits |
| `portfolios` | Owner-scoped portfolio metadata, CSV validation, snapshot resolution/storage and dated review |
| `ledger` | Immutable transactions, corrections, FIFO, valuation, returns and risk |
| `watchlists` | Private bookmarks, preferences and bounded market-information loads |
| `market_data` | Provider-independent contracts, Intrinio transport and validation |
| `research` | Research forms/views, analysis presentation, charts and shared templates |
| `operations` | Shared request admission and database backup tooling |
| `scripts`, `deploy` | Local database helper and production build/start configuration |
| `tests` | Calculation, provider, page, database, browser and runtime checks |

## Request and calculation flow

Views validate input and ownership before services perform work. Provider responses are
converted into bounded, validated contracts; pure calculation modules do not make
network requests. Templates display source dates, units, assumptions and unavailable
states alongside results.

Portfolio calculations read the current effective journal after corrections. FIFO and
historical cutoff logic derive positions and cash; prices are loaded only when required
by an explicit valuation or performance action. Totals are derived rather than stored as
independently editable balances. Internal journal snapshots provide a consistent input
to calculations; they are separate from supplied holdings snapshots.

The snapshot workflow validates CSV locally, then performs explicit bounded search
and reference-validation actions. A signed, user-bound payload carries inputs for
15 minutes without session or raw-file storage. Separate snapshot/holding models
store only confirmed inputs; no journal entries are created. Snapshot review copies
inputs consistently before provider I/O, then computes values and concentration
in a separate pure contract. Prices and calculated results are never persisted.
Owner-row locks serialize saves, capacity checks and deletion. Unique submission
receipts provide retry identity and prevent stale retries from restoring a deleted
snapshot. Review reads use the same owner lock only while copying inputs, then
release it before price requests; post-load authorization detects deletion during I/O.
See [snapshot contracts](holdings-snapshots.md).

Money uses Decimal and defined rounding. Statistical calculations use exact rational
inputs where appropriate, with rounding at the display boundary. Chart coordinates never
feed financial calculations. See [methodology](methodology.md).

## Integrity and authorization

Private records are scoped to the authenticated owner. Forms retain CSRF and method
checks; foreign private identifiers return private unavailable/not-found responses
rather than another owner's data. PostgreSQL constraints, locks and immutable-entry
guards protect journal writes. Corrections retain originals and validate the resulting
history before committing.

An append retry with the same idempotency key and identical contents returns the
existing entry. The service rechecks that key after a failed preflight, because another
request may have committed between the initial key lookup and replay. Conflicting keys
or invalid downstream balances remain errors.

SQLite supports the research/account foundation and transient CSV checking. It cannot substitute for
PostgreSQL tests of row locking, concurrency or ledger integrity.

## Data access and serving

The Intrinio adapter enforces fixed hosts, verified TLS, response bounds, identity/unit
validation and credential redaction. No automatic retries, prefetching or
successful-response cache is implemented. Production request admission uses PostgreSQL
so limits survive worker restarts and apply across workers. See
[integration](intrinio.md) and [safeguards](release-safeguards.md).

Gunicorn serves Django; WhiteNoise serves collected static assets. Production defaults
to private access and closed registration. HTTPS proxy trust is explicit. The health
endpoint checks process liveness only. See [serving](production-serving.md) and
[Render/Neon operations](render-deployment.md).

## Design rationale

A single Django application keeps forms, authentication, persistence and HTML within one
stack. Small local chart scripts and SVG preserve accessible tables without a separate
frontend build. Keeping financial arithmetic independent of HTTP and persistence makes
formulas testable against hand-calculated examples. PostgreSQL supplies transactional
integrity and shared limits without requiring an additional cache or queue service.
