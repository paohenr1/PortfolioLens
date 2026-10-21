# Render and Neon operations

The application uses Render for the web service and Neon PostgreSQL for durable records.
Releases are manual. This guide describes configuration and checks; it does not attest
to the current dashboard settings or deployment health.

## Verify the release target

Before each release, inspect Render's selected repository, branch and commit. Do not
infer the deployed branch from GitHub's default branch or from a merged PR. The
[blueprint template](../deploy/render.yaml.template) names `main`, but it is a reference
template, not a readout of the running service. Keep deployment and preview automation
disabled unless intentionally changing the release process.

Review source changes, migration implications, configuration and rollback before
selecting a commit. Publishing a PR does not deploy it.

## Build and runtime

- Build: `bash deploy/render-build.sh`
- Start: `.venv/bin/python scripts/start_production.py`
- Health check: `/health/live/`
- Python: use the version specified by the reviewed deployment template.

The build installs pinned uv and locked runtime packages, checks production
configuration and collects/validates static assets. It does not migrate, seed, create
users, query the database or call Intrinio. Worker startup also performs no migrations
or account creation. Render supplies `PORT`; the managed service binds `0.0.0.0`. Start
with one worker and measure memory/request latency before increasing it. See [runtime
details](production-serving.md).

## Secure configuration

Use [production.env.example](../deploy/production.env.example) and secure service
settings. Keep the application secret stable, debug disabled, hosts explicit, private
access enabled, registration closed and shared PostgreSQL limits enabled. The
application accepts individual database fields, not `DATABASE_URL`.

Require `DJANGO_DATABASE_SSLMODE=verify-full` and a trusted CA available to libpq.
Verify the actual database hostname/certificate. Do not copy development proxy
certificates or placeholder credentials into Render.

Use Neon's direct endpoint for migrations and backup/restore tooling. Its pooled
endpoint uses transaction pooling and has session-feature restrictions; evaluate pooling
separately with ledger and shared-quota concurrency checks. The current application uses
`CONN_MAX_AGE=0`.

Enable `DJANGO_TRUST_PROXY_HTTPS` only after verifying that ingress replaces
`X-Forwarded-Proto` and blocks direct external application access. Behind verified TLS
termination, this setting must match ingress behavior to avoid redirect loops. It does
not establish trust in forwarded client addresses.

## Database operations

Use a trusted operator machine with the locked checkout and securely loaded settings if
the selected Render tier has no shell or one-off jobs. Inspect the intended database and
migration plan before applying changes:

```sh
uv sync --frozen --no-dev
uv run --frozen --no-dev python manage.py check --deploy
uv run --frozen --no-dev python manage.py migrate --plan
```

Apply migrations as a separate controlled operation using the intended migration role.
Provision accounts through Django management tools when needed. Keep the runtime role
separate from provider administration and do not seed test fixtures. For incompatible
migrations, plan write downtime and recovery before proceeding. Do not assume that
rolling application code back reverses a database migration.

## Operational limits and recovery

Free tiers can sleep, cold-start, suspend on usage limits and change their allowances.
Verify current account limits, payment settings and provider terms before releases. A
build spending limit is not a universal billing cap. The web filesystem is ephemeral;
account, journal and watchlist records belong in PostgreSQL. Do not use keep-awake
traffic to circumvent provider sleep policies.

The health endpoint is process-only: it proves neither database readiness nor Intrinio
access. It avoids continuous database probes. A busy synchronous worker can delay health
checks, so measure behavior on the selected instance.

[Backup/export and isolated recovery tooling](backups.md) exists, but the repository
does not configure scheduled off-machine backups, retention or a recovery-time
objective. Do not infer backup coverage from these scripts or a database provider's
short restore history.

For a release, verify HTTPS and redirects, sign-in, anonymous access restrictions,
closed registration, static assets, ownership, database TLS and representative
functional behavior. Provider checks require appropriate entitlements and a bounded
request budget. Record actual results separately from local test results.

## Provider references

Recheck current terms and configuration guidance rather than relying on saved allowance
figures:

- [Render free services](https://render.com/docs/free)
- [Render Blueprint specification](https://render.com/docs/blueprint-spec)
- [Render health checks](https://render.com/docs/health-checks)
- [Neon connection security](https://neon.com/docs/connect/connect-securely)
- [Neon connection pooling](https://neon.com/docs/connect/connection-pooling)

## Runtime-role permissions before deployment

After the selected release's migrations have been applied separately, load the exact
runtime database settings securely and run from that release checkout:

```sh
uv run --frozen --no-dev python manage.py check_runtime_permissions
```

Run this as the web application's runtime role, not the migration owner or an
administrator: an owner passing the check does not establish runtime access. Repeat
after migrations or role/grant changes, before directing traffic to the release.
A nonzero exit blocks this verification; have the database operator review the named
missing permissions through the normal controlled process, then rerun. This command
never issues grants, migrations, writes, or sequence increments and prints no connection
credentials or user records. Do not run the automated test suite against production.

The check inspects effective privileges (including inherited and PUBLIC grants) on
managed Django model tables, including automatically created relationship tables, in
the connection's search path. Its baseline requires SELECT/INSERT/UPDATE/DELETE on
mutable application and session tables; SELECT/INSERT on immutable journal and
correction tables; and SELECT on Django permission/group/content-type reference tables.
It also checks schema USAGE and USAGE or UPDATE on serial/identity sequences needed
for generated IDs. It does not require schema CREATE, table ownership, TRUNCATE, or
administrative rights. It excludes migration history and does not certify row-level
security policies, trigger/function permissions, provider availability, or every
application operation. Follow it with the representative functional release checks
above. A process-only healthy response cannot detect missing table or sequence grants.
