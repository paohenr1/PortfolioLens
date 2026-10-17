# Request admission and production safeguards

Production uses shared PostgreSQL admission for market-data calls and account write
attempts. Configuration guards reject unsupported production settings.

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

`DJANGO_TRUST_PROXY_HTTPS=false` is the default. Set it to true only in production after
confirming that the trusted ingress strips/replaces `X-Forwarded-Proto` and direct
external access to the application is blocked. This uses Django's standard HTTPS proxy
setting and avoids redirect loops behind TLS termination. It does not trust forwarded
client addresses, establish an ingress access rule, enable cross-origin access or verify
a hosting provider. Do not enable it merely because a host uses a proxy.

```sh
uv run --frozen python scripts/check_release_configuration.py
```

This runs Django's actual deployment checks in an isolated child using temporary
synthetic application/database configuration. It makes no provider or hosted
database connection and never prints credentials. All unexpected warnings/errors
fail the command. Two findings are printed and intentionally retained:

- `security.W005`: HSTS does not cover all sibling subdomains. Their HTTPS is
  not verified, so we do not force a domain-wide policy.
- `security.W021`: browser HSTS preload is disabled. Preload requires a separately reviewed domain policy.

The checks are not silenced in normal Django settings. They are documented
policies, not failures to fix by enabling unverified domain-wide behavior.
Selected-host checks must repeat with its real configuration and connectivity.

## Limitations

Shared admission covers processes using the same database, not every deployment sharing
a subscription. Liveness and synthetic configuration checks do not establish hosted TLS,
data rights, backup recovery or functional readiness.

See [setup and checks](setup.md#automated-checks) and the [methodology
index](methodology.md) for related calculations.
