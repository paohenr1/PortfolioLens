# Production serving

Gunicorn and WhiteNoise provide the runtime for the existing Django application. See
[Render and Neon operations](render-deployment.md) for release procedures.

## Runtime and private access

Gunicorn 26.2.0 serves the WSGI application. WhiteNoise 6.12.0 serves collected,
fingerprinted, compressed static assets; no Node build, CDN or separate static
service is needed. Both are free software, resolved from PyPI and pinned with
artifact hashes in the existing lockfile. Django remains 5.2 LTS on Python 3.12.

Production defaults to `DJANGO_PRIVATE_SITE=true` and `DJANGO_ALLOW_REGISTRATION=false`.
Anonymous research requests redirect to sign-in before provider work, including search
and direct instrument routes. Active sessions can use research; inactive users lose
access. Registration is 404 for anonymous users, and account-creation links are hidden.
Existing private portfolio/watchlist owner checks still apply. Development defaults stay
public with registration available for local workflows.

An operator must provision the initial user through Django's management tools in the
configured deployment. Disabling the private gate or reopening registration is an
explicit configuration change requiring a reviewed access policy and applicable data
rights. These defaults alone do not prove that an Intrinio individual plan permits a
particular hosted deployment.

Private-site HTML, redirects and errors are no-store. Static files retain their
public cache policy and the application's security headers. No provider response
cache or new financial dataset is introduced.

## Build and start

Use [the production settings template](../deploy/production.env.example), not the
development `.env.example`. Supply real values securely in the chosen host's settings.
Do not commit secrets or copy development proxy placeholders into another host.
Database/user/host/password, explicit app hosts, the persistent application secret and
verified database TLS must be configured.

From the checkout, after loading those settings through the host's supported
secure mechanism:

```sh
uv sync --frozen --no-dev
uv run --frozen python manage.py collectstatic --noinput
uv run --frozen python manage.py check --deploy
# A separate controlled release operation, before application traffic:
uv run --frozen python manage.py migrate --noinput
# Process command; validates production configuration and collected assets:
uv run --frozen python scripts/start_production.py
```

These are operator commands for a configured target. Production `check --deploy` retains
the two documented HSTS subdomain/preload advisories, without silencing unexpected
findings. The separate synthetic `scripts/check_release_configuration.py` command is a
configuration regression, not a real-host connectivity test.

The entry point rejects development mode, weak/invalid production configuration,
missing or invalid static manifests and hidden `GUNICORN_CMD_ARGS` overrides.
It replaces its process with Gunicorn; it does not migrate, seed records or
create accounts on every worker start. Required stylesheet/script manifest paths
must resolve to existing files inside `staticfiles`.

| Setting | Default / accepted range |
| --- | --- |
| `STOCK_BIND_HOST` | `127.0.0.1`; explicit `0.0.0.0` is also supported for a reviewed managed ingress |
| `PORT` | 8000; unprivileged numeric port 1024–65535 |
| `STOCK_WORKERS` | 1; 1–4, chosen according to actual host memory/CPU |
| Worker | synchronous WSGI, no application preload |
| Request/graceful timeouts | 180 / 30 seconds |
| Worker renewal | 500 requests plus up to 50 jitter; PostgreSQL quotas do not reset |

Start with one worker for a small free instance and measure memory before
increasing it. Multiple workers need the already implemented shared PostgreSQL
admission. Access logs are disabled to avoid routinely logging account/query
URLs. Fixed application errors and existing credential redaction remain in place.

Gunicorn's implicit trust of forwarded HTTPS headers is disabled. Django alone
applies the explicit `DJANGO_TRUST_PROXY_HTTPS` policy, default false. Enable that
flag only after verifying the selected ingress replaces the header and blocks
direct external app access. Otherwise a default loopback trust could make a
supplied header bypass the application's own policy. Forwarded client addresses
remain untrusted; callers behind one proxy share its client allowance.

## Health checks and free-tier behavior

`GET` or `HEAD /health/live/` returns only `{"status":"alive"}`. It makes no
database or provider query, includes no configuration/user details and is
no-store. This exact process-only path is exempt from HTTPS redirection so a
controlled internal process probe can use plain HTTP; other routes retain the
production HTTPS policy. POST is rejected. Host validation still applies.

Liveness proves only that the process is responding. It does not prove the
database, migrations, Intrinio access or backup recovery works. It avoids
continuous database probes that prevent Neon from suspending after inactivity.
Do not use synthetic traffic to circumvent a provider's free-instance sleep
policy. Perform database/functional readiness checks deliberately on the chosen
host before opening access, with its real TLS configuration.

## Verification

```sh
uv run --frozen --env-file .local/database-test.env python manage.py test tests.test_production_serving tests.test_environment tests.test_release_safeguards --noinput
uv run --frozen python tests/production_smoke.py
```

The smoke test collects static assets and starts temporary Gunicorn processes with
synthetic settings. It checks private access, proxy-header handling, secure cookies,
static caching and unavailable-storage behavior. It does not prove real HTTPS
termination or successful production database access. Hosted checks must use the
intended configuration and explicit operational scope.
