# Development setup and testing

## Requirements

Use Python 3.12 and uv; CI pins uv 0.12.19. Dependencies and artifact hashes are locked
in `uv.lock`. No Node build is required. PostgreSQL is required for portfolios and
watchlists. The local database helper requires Docker and a Unix-socket-capable
environment. An Intrinio key is required only for live data.

Run all commands from the repository root:

```sh
uv sync --frozen
python3 scripts/development_database.py
uv run --frozen --env-file .local/database.env python manage.py migrate --noinput
uv run --frozen --env-file .local/database.env python manage.py check
uv run --frozen --env-file .local/database.env python manage.py runserver 127.0.0.1:8000 --noreload
```

The helper uses a pinned PostgreSQL image, no published TCP port, and an owner-only Unix
socket. It preserves recognized data and refuses mismatched container settings. The
application and test roles are separate: the test role can create disposable databases
and cannot connect to development storage. See [database configuration and
ownership](portfolios.md).

The development server is local only. These instructions do not restart or change a
deployed service. Use an available local port if 8000 is occupied.

## Environment configuration

Django does not automatically read `.env`. If no local `.env` exists, copy
[`.env.example`](../.env.example), edit it privately, and supply it to uv:

```sh
uv run --frozen --env-file .env --env-file .local/database.env python manage.py check
uv run --frozen --env-file .env --env-file .local/database.env python manage.py runserver 127.0.0.1:8000 --noreload
```

The generated database file takes precedence over `.env`. Existing process variables
take precedence over dotenv values. Do not overwrite existing files. Keep keys, database
credentials, exports and private data out of Git and logs.

| Variable | Development behavior | Production requirement |
| --- | --- | --- |
| `DJANGO_ENV` | Defaults to `development` | Set `production` |
| `DJANGO_DEBUG` | Defaults true | False; true is rejected |
| `DJANGO_SECRET_KEY` | Generated per process if absent | Persistent, securely generated key; at least 50 characters, five distinct characters, no insecure prefix |
| `DJANGO_ALLOWED_HOSTS` | Loopback hosts | Explicit hostnames; no wildcard, scheme, path or port |
| `INTRINIO_API_KEY` | Optional; live data otherwise unavailable | Backend-only credential with appropriate entitlements |
| `DJANGO_DATABASE_ENGINE` | Defaults to SQLite | PostgreSQL |
| `DJANGO_RATE_LIMIT_BACKEND` | Memory | PostgreSQL shared admission |
| `DJANGO_PRIVATE_SITE` | Defaults false | Defaults true |
| `DJANGO_ALLOW_REGISTRATION` | Defaults true | Defaults false |
| `DJANGO_TRUST_PROXY_HTTPS` | Defaults false | Enable only for verified ingress behavior |

See [PostgreSQL variables](portfolios.md#database-settings) and [production
settings](../deploy/production.env.example). Local socket trust must never be used for
an externally accessible database. Production requires verified database TLS
(`verify-full`). A stable local secret is needed to keep sessions valid across
development-process restarts.

## Verify local behavior

The home page and empty search form load without an Intrinio key. Submitted searches
require the key and show an explicit unavailable state when absent. A configured key
alone does not prove authentication or dataset access.

Development registration is available by default. Create a local account to use
portfolios and watchlists. Opening lists and accounting pages does not request market
prices; pricing and analysis loads are explicit.

For research/accounts-only experimentation, omit the PostgreSQL environment file and
migrate SQLite. Persistent portfolio/watchlist routes then return an explicit unavailable
response. The transient holdings CSV checker requires authentication but not PostgreSQL.
SQLite cannot verify PostgreSQL integrity or concurrency.

## Automated checks

Use only an isolated local/test database for the suite:

```sh
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen --env-file .local/database-test.env python manage.py check
uv run --frozen --env-file .local/database-test.env python manage.py makemigrations --check --dry-run
uv run --frozen --env-file .local/database-test.env python manage.py test --noinput
uv run --frozen python scripts/check_release_configuration.py
uv run --frozen python tests/production_smoke.py
```

The suite covers independent financial examples, malformed/missing provider
observations, ownership, CSRF, corrections, concurrency and database guards. Ordinary
tests use synthetic data and do not need live credentials. CI also runs SQLite
compatibility and static collection. Report skipped PostgreSQL tests separately from
passes.

[Acceptance checks](release-acceptance.md) describe optional browser runners. They
require Playwright and Chromium separately from the locked application runtime.
Live-provider checks are opt-in and consume provider requests.

## Troubleshooting

- **Private storage unavailable:** check that PostgreSQL is running and that the
  command uses the intended local environment file. Do not substitute production
  credentials to make development tests pass.
- **Provider unavailable:** check secure key configuration and endpoint
  entitlements. Do not log authenticated URLs or raw error bodies.
- **Rate limit:** honor the displayed retry delay; loads share request budgets.
- **Missing static assets in production:** use the documented build/collection
  process; the production entry point validates the manifest.
- **Database helper refuses to start:** inspect its ownership/container mismatch
  message. Do not delete existing data to bypass the guard.
