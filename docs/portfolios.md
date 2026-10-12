# Private portfolios and PostgreSQL

Version 0.6 adds portfolio metadata: create, list, and view your own portfolios.
Version 0.7 adds the [transaction journal](ledger.md) and derived recorded cash.
Version 0.8 adds [FIFO positions, cost basis, and realized sale gains](fifo.md).
Version 0.10 adds [market valuation and unrealized gains](valuation.md) with an
explicit date and price load. Version 0.11 adds [cash-inclusive allocations](allocations.md).
Version 0.12 adds [time-weighted returns](performance.md) for supported end-of-day flows.
Reporting currency is an explicit USD choice; FX support is deferred.

## Local development

Use Python 3.12, uv, and a running local Docker daemon. The cloud already
provides Docker. From the repository root:

```sh
export UV_CACHE_DIR=/workspace/.cache/uv
uv sync --frozen
python3 scripts/development_database.py
uv run --frozen --env-file .local/database.env python manage.py migrate --noinput
uv run --frozen --env-file .local/database.env python manage.py check
uv run --frozen --env-file .local/database.env python manage.py runserver 127.0.0.1:8002 --noreload
```

The helper pins the official PostgreSQL 16 image by digest, checks the managed
local Docker socket, creates only its named development container, and reuses
recognized data. It refuses mismatched container labels/mounts/settings,
symlinked directories, unexpected database files, and paths too long for Unix
sockets. It does not delete or replace an existing database. Existing generated
environment files are preserved. First initialization waits for the final
server, not the entrypoint's temporary bootstrap server.

Data is in ignored `.local/postgres/data`. The socket is in
`.local/postgres/socket`. The container runs as the task user's UID/GID with
`--network none`, no published ports, no TCP listener, and a private socket
directory. Local socket trust is only for this development setup: another
process running as the same OS user can impersonate a database role. This is
not production database authentication, isolation, backup, or hosting.
Containers need restarting in new tasks; retained files alone do not start
PostgreSQL. The helper is idempotent and preserves data over container restarts.
Database major-version upgrades require a separate migration/backup plan.

The application role `stock_research` has neither superuser nor CREATEDB
privileges. The separate `stock_research_test` role can create disposable test
databases and cannot connect to the development database. Bootstrap/admin
access stays separate from the app connection. PostgreSQL role separation does
not replace application owner checks.

This starts a separate PostgreSQL database and preserves the original
`db.sqlite3`. It does not automatically copy SQLite accounts or sessions.
The inspected development SQLite database had zero accounts at this milestone,
so there were no existing users to transfer. A machine with existing account
data needs a separately verified migration before switching its users.

Without database settings, research/accounts still use SQLite. Portfolio
routes then return HTTP 503 with an explicit unavailable state and no writes.
Production requires PostgreSQL and fails closed instead of using SQLite.

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
appropriate certificate trust. No remote database connection, production
credentials, or deployment has been configured. Configuration failures do not
echo supplied values. Connections have a five-second connection timeout;
query/lock timeout policy and production pooling remain operational work.
Never print settings dictionaries containing passwords.

To combine an existing local `.env` with the generated private database
configuration, supply `--env-file .env --env-file .local/database.env` to uv;
the generated database file takes precedence. Cloud Intrinio bindings remain
inherited. Do not overwrite an existing `.env` or reuse the local socket trust
scheme for an externally accessible database.

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

## Verification

```sh
uv run --frozen --env-file .local/database-test.env python manage.py test --verbosity 2
python3 tests/browser_portfolios.py
```

The full suite passes 518 tests on PostgreSQL with no skips. Added checks cover
database configuration and TLS rules, owner isolation, owner-ID injection,
CSRF enforcement, escaping, name/currency validation, pagination, database
constraints, protected owner deletion, and actual concurrent name/allowance
creation. Test databases are created and destroyed separately from development
data. A SQLite-only run skips 216 PostgreSQL portfolio/ledger/watchlist/correction tests; it is
not portfolio acceptance. The selected SQLite foundation/guard suite passes
51 tests separately.

The browser runner uses preinstalled Playwright/Chromium and creates its own
temporary PostgreSQL database under the test role. Two real browser sessions
create/list/view their own portfolios and receive 404 for the other owner's
UUID. Duplicate validation, sign-out, keyboard controls, and desktop/mobile
layouts are checked. The actual Python child receives termination, closes its
connections, and removes only its generated test database. Normal startup
does not use this server or browser accounts. Screenshots are under
`/tmp/stock-portfolios-*.png`; diagnostics are at
`/tmp/stock-portfolio-server.log`. No market-data requests occur.

Fresh bootstrap, repeated setup, and container restart were also exercised in
a disposable cluster with a retained sentinel row. The main development role
and test-role isolation were verified. GitHub Actions now specifies the same
pinned PostgreSQL image and full suite; remote workflow execution has not been
observed. Its synthetic credential is only for a disposable CI service.

No paid database service or extra Intrinio calls were introduced. The only new
Python dependency is Psycopg 3 with its binary distribution, frozen in uv.lock.
Operational backups/restore, public deployment, broader currency support,
complex corporate actions, money-weighted and annualized returns remain pending.

The append-only USD ledger is implemented, including historical balance checks,
explicit ordering, fees, and portfolio-scoped idempotency. FIFO positions and
realized gains and recorded dividends/splits are also implemented. Market
valuation and unrealized gains now use explicit matching dates and missing-data
checks. Allocation weights reuse complete valuations; time-weighted returns
use explicit periods and supported end-of-day flow timing. Private [watchlists](watchlists.md) are implemented. Explicit [corrections](corrections.md) are implemented. Bounded [daily session returns](daily-returns.md) are implemented. Observed [volatility and drawdown](risk.md) are implemented. Next: benchmark comparison with aligned sessions.
