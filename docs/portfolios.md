# Private portfolios and PostgreSQL

Create, list and view private USD portfolios. Each portfolio links to its [transaction
journal](ledger.md), [FIFO positions](fifo.md), dated [valuation](valuation.md),
[allocations](allocations.md), [time-weighted returns](performance.md) and [daily
returns/risk](daily-returns.md). Reporting currency is an explicit USD choice; FX is
unsupported.

## Local development

Follow [setup](setup.md) to create the private local PostgreSQL container and separate
application/test roles. The helper preserves recognized data and does not migrate SQLite
accounts automatically. Local socket trust is restricted to the owner-only directory and
is not suitable for production.

## Database settings

| Variable | Meaning |
| --- | --- |
| `DJANGO_DATABASE_ENGINE` | `sqlite` for the foundation, or `postgresql` for private portfolios; PostgreSQL required in production |
| `DJANGO_DATABASE_NAME` | Required PostgreSQL database identifier |
| `DJANGO_DATABASE_USER` | Required PostgreSQL role identifier |
| `DJANGO_DATABASE_HOST` | Required hostname/IPv4 or development Unix socket directory |
| `DJANGO_DATABASE_PORT` | 1–65535, default 5432 |
| `DJANGO_DATABASE_PASSWORD` | Configure securely; required in production, empty for the private local socket |
| `DJANGO_DATABASE_SSLMODE` | Development defaults `disable`; production requires `verify-full` |
| `DJANGO_DATABASE_SSLROOTCERT` | Optional trusted CA file path for libpq certificate verification |

Remote production connections require a password, TCP host, verified TLS, and
appropriate certificate trust. Configuration failures do not echo supplied values.
Connections have a five-second connection timeout; query/lock timeout policy and
production pooling remain operational work. Never print settings dictionaries containing
passwords.

To combine an existing local `.env` with the generated private database configuration,
supply `--env-file .env --env-file .local/database.env` to uv; the generated database
file takes precedence. Existing process environment variables remain inherited. Do not
overwrite an existing `.env` or reuse the local socket trust scheme for an externally
accessible database.

## Ownership and storage rules

`Portfolio` stores a UUID primary key, protected owner foreign key, a 100-character
name, USD reporting denomination, and UTC creation timestamp. The owner/date
index supports owner-scoped pagination, twenty portfolios per page.

All three routes require sign-in. Every list/detail query filters by
`request.user`; owner IDs and UUIDs submitted in a form or query do not select
another owner. UUIDs are not an authorization mechanism. Foreign and missing
UUIDs return the same generic HTTP 404 page. Private routes, including routing
errors and CSRF failures, send no-store headers. Create is a CSRF-protected
POST; list/detail are GET-only. There are no edit, transfer, or delete routes.
Names are escaped in HTML and authentication remains Django session-based.

Names are trimmed, cannot be blank or contain control characters, and must be
unique within the owner under PostgreSQL `LOWER(TRIM(name))`. Different owners
may use the same name. Database constraints also reject non-USD denomination,
blank names, duplicate names, and orphan owners. Owner deletion is protected
until a retention/deletion policy is defined for ledger data.

Each account can create up to fifty portfolios. Creation locks the owner row
inside a transaction before counting/inserting, so concurrent requests cannot
exceed the allowance. The database uniqueness constraint also handles racing
names; the form reports the conflict without exposing raw database errors.
This is a bounded metadata foundation, not comprehensive distributed abuse
control. Open registration and production auth limits remain as documented in
[authentication](authentication.md).

## Limitations

Portfolio analysis requires transaction history; creating metadata alone does not create
holdings. Storage and concurrency guarantees require PostgreSQL. Holdings import is not
implemented.

See [setup and checks](setup.md#automated-checks) and the [methodology
index](methodology.md) for related calculations.

## Portfolio overview

The portfolio overview shows recorded cash, remaining FIFO cost, realized sale gain/loss
and the first five open holdings directly from one effective journal snapshot. Opening
it makes no provider request and writes no totals. A separate inline section updates
closing market value, unrealized gains and time-weighted returns with one CSRF-protected
submission. Opening/closing dates and the existing cash-flow/share-basis confirmation
are explicit; detailed valuation and risk pages remain available for deeper analysis.

The combined load takes one owner-scoped journal snapshot and uses the existing
performance plan and bounded prices. Its closing valuation is reused without an extra
price request. If timing or performance-plan limits fail before price I/O, closing
valuation alone is attempted with its existing five-instrument limit, and the return
stays unavailable with an explanation. A supported plan retains the eight-request
limit and stops after rate exhaustion, preserving Retry-After. Missing closes withhold
unknown totals. Recorded journal totals include all entries; market values explicitly
stop at the selected closing date. No pricing cache or automatic refresh is introduced.

The transaction entry form shows type-specific inputs when JavaScript is available,
retaining values when switching types but omitting inactive inputs on submission.
Field errors remain visible. Without JavaScript the full server-validated form remains
usable. Submission identity, exact arithmetic, CSRF and correction behavior are unchanged.

The My Portfolio navigation opens the overview directly when the signed-in owner has
exactly one portfolio; zero or multiple portfolios lead to the portfolio list. The
overview keeps one holdings table, puts loaded value/return figures first, and reserves
methodology and advanced analysis links for secondary details. Important dates, input
confirmations, missing-price warnings and provider errors remain visible.
