# Release safeguards

Version 0.30, October 11, 2026. This closes the release-safeguards work package
after [acceptance](release-acceptance.md). Deployment, hosting costs, real HTTPS
ingress, hosted database TLS and off-machine backup storage remain to be verified
on the chosen private host. The original specification is unchanged.

## Shared admission without an additional service

Production requires `DJANGO_RATE_LIMIT_BACKEND=postgresql`; that is its default.
Explicit memory mode is rejected in production. Development defaults to its
existing memory counters and can opt into PostgreSQL for integration checks.
Both backends use the same limits:

| Scope | Per client per minute | Total per minute |
| --- | --- | --- |
| Intrinio backend requests | 10 | 30 |
| Registration/sign-in/password-change POST attempts | 10 | 60 |

The additive `operations/0001_initial` migration creates two possible counter
rows, keyed by scope. No historical price/financial dataset or new Redis service
is stored. Each row keeps a database-clock minute, a total and bounded SHA-256
client hashes/counts. Denied clients are not added, limiting the dictionaries to
30/60 entries. The hashes are identifiers for admission, not anonymization.

Reservations use a durable transaction and row lock. Initial-row creation races
and unique-client floods are bounded atomically. PostgreSQL's clock gives all
workers/restarts the same window; moving the clock backward does not clear an
allowance. A forward minute change resets the bounded state on next admission.
Lock/statement timeouts are two/three seconds. Provider/authentication work
begins after the reservation commits and releases all locks. Reservations cannot
be placed inside a business transaction whose rollback could refund a call.
Failed provider requests still spend their allowance.

Missing tables, database errors, invalid state, unsupported storage or an outer
transaction fail closed. Market pages return their existing fixed no-store 503;
account writes return a fixed no-store 503 and do not authenticate, register or
change passwords. There is no automatic retry or memory fallback. Genuine quota
exhaustion keeps 429 and `Retry-After`. Migration is required before traffic.

Only `REMOTE_ADDR` identifies clients; forwarded address headers remain
untrusted. Clients behind one reverse proxy therefore share its client allowance
until the selected ingress supplies a separately verified identity strategy.
The global allowance applies across all processes sharing this database.
Separate databases/deployments sharing one Intrinio subscription do not share
this allowance; account-wide limits and subscription rights still need review.

## Production configuration and HTTPS

Existing fail-closed production guards remain: explicit hostnames, a strong
secret, debug off, PostgreSQL with a password and `verify-full` TCP TLS, secure
session/CSRF cookies, HTTPS redirect, no-store private responses, secret-redacted
logs and a short initial HSTS duration. SQLite cannot be production storage.

New `DJANGO_TRUST_PROXY_HTTPS=false` is the default. Set it to true only in
production after confirming that the trusted ingress strips/replaces
`X-Forwarded-Proto` and direct external access to the application is blocked.
This uses Django's standard HTTPS proxy setting and avoids redirect loops behind
TLS termination. It does not trust forwarded client addresses, establish an
ingress access rule, enable cross-origin access or verify a hosting provider.
Do not enable it merely because a host uses a proxy.

```sh
export UV_CACHE_DIR=/workspace/.cache/uv
uv run --frozen python scripts/check_release_configuration.py
```

This runs Django's actual deployment checks in an isolated child using temporary
synthetic application/database configuration. It makes no provider or hosted
database connection and never prints credentials. All unexpected warnings/errors
fail the command. Two findings are printed and intentionally retained:

- `security.W005`: HSTS does not cover all sibling subdomains. Their HTTPS is
  not verified, so we do not force a domain-wide policy.
- `security.W021`: browser HSTS preload is disabled. Enrollment is not justified
  for an undeployed hostname.

The checks are not silenced in normal Django settings. They are documented
policies, not failures to fix by enabling unverified domain-wide behavior.
Selected-host checks must repeat with its real configuration and connectivity.

## CI and verification

The existing workflow keeps pinned actions, a pinned PostgreSQL service, frozen
dependencies, least-privilege read access, lint/format, migrations, the full real
PostgreSQL suite and static collection. It now runs production configuration
guards and a separate SQLite compatibility pass with PostgreSQL options cleared.
No market-data secret, live acceptance or new paid CI service is required.
Commands were verified locally; remote GitHub Actions has not been executed.

```sh
uv run --frozen --env-file .local/database-test.env python manage.py test tests.test_release_safeguards tests.test_backups --noinput
python3 tests/browser_release_journey.py --shared-limits
uv run --frozen python scripts/verify_backup_restore.py --local-container
```

There are 25 new automated checks: five configuration/HTTPS cases, twelve real
PostgreSQL admission cases and eight archive-safety cases. They include concurrent
same-client/global floods, initial creation races, actual separate Python workers
sharing an allowance, rollover/backward-clock behavior, durable boundaries,
storage-failure denial before provider I/O/account mutation, malformed counters,
exclusive private archives, interruption cleanup, replacement-file protection,
TLS/password forwarding and safe errors. The connected browser journey passes
with both memory and PostgreSQL admission, including corrections and funding.
Its synthetic provider transport and generated databases remain test-only.

PostgreSQL: 982 pass without skips. SQLite: 982 discovered, 690 pass and 292
PostgreSQL-only cases skip. Focused safeguards: 25 pass. Ruff lint/format checks
207 Python files. Frozen setup, additive migration, no migration drift,
Django/static and fresh normal readiness checks pass. Development business
records stay empty; owned browser/drill databases and synthetic archives are
removed. No authenticated provider call or new dependency was needed here.

## What remains

The [backup export and restore drill](backups.md) now pass, including exact row
digests, password hashes, correction links, watchlist preferences, sessions,
schema history, restored journal immutability and private owner checks. Scheduled
encrypted off-machine copies, retention and recovery timing remain host-specific.

One planned private-MVP work package remains: choose a low-cost deployment target,
prepare its process/static serving, HTTPS, role/TLS configuration and persistent
storage/backups, confirm applicable Intrinio display/storage rights, then run a
controlled private deployment and smoke checks. This is a work package, not a
promise of a fixed duration or permanent free hosting. Broader market coverage
and optional advanced specification features remain separate scope.
