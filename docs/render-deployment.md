# Render + Neon deployment draft

Prepared October 12, 2026, for the existing v0.31 application. This is a reviewable
candidate, not a selected or provisioned host. No resource, account, source push,
database migration, public endpoint or charge has been created.

## What is prepared

[The blueprint template](../deploy/render.yaml.template) specifies one native
Python **Free** web service, one worker, private research, closed registration,
a process-only health check, manual deployment and automatic previews disabled.
It declares no Render
database, disk, background worker, cron service or paid plan. PostgreSQL remains
external: the candidate is Neon Free, subject to its actual account allowances.
It is deliberately named `.template` so it cannot become a default root
`render.yaml` deployment by accident.

[The build script](../deploy/render-build.sh) requires Python 3.12, installs the
same pinned uv version as CI into a checkout-local tool environment, installs
locked runtime packages, runs production configuration checks and collects
compressed static assets. It validates the same manifest/server configuration
as the production entry point. It does not migrate, seed, create users, query
the database or call Intrinio. The start command uses the installed application's
Python directly, so Render does not need a globally installed uv executable.

The template uses Python 3.12.14, the interpreter tested in this environment.
Render's current version documentation supports specifying any released version
from 3.7.3 onward using the full `PYTHON_VERSION`. Actual remote build remains
unrun. `PORT` comes from Render;
the application binds `0.0.0.0` behind the selected ingress. Initial worker count
is one. Measure memory on the actual free instance before increasing it.

## Verified terms and remaining account checks

The saved `render.com` addition is now in the running desired policy and
`https://render.com/docs/free` returns **HTTP 200** through the configured proxy.
Free terms, pricing, the Blueprint reference/schema, Python version settings,
health checks and web-service port/TLS behavior were read on October 12, 2026.
The runtime still reports network state `unknown`; successful specific requests
are evidence of those operations, not of all desired policy enforcement.

The updated template passes Render's current official JSON schema. It uses
`autoDeployTrigger: "off"` instead of deprecated `autoDeploy`, and explicitly
disables preview generation. The downloaded schema's SHA256 was
`8a3fb8da6b4f55fe686fbefa790e011d3dd7895f013f355953c572a21ab6494a`.
This is local validation against a public schema, not an account/API apply.

Render Free has 512 MB RAM, 0.1 CPU in its Blueprint reference, 750 shared free
service-hours/month, 15-minute idle sleep and roughly one-minute cold starts.
Hobby includes 5 GB outbound traffic and 500 build minutes/month. Render explicitly
advises against Free for production. It can suspend a service for unusually heavy
external traffic, including Neon/Intrinio calls, without publishing a numeric
threshold. See the [full comparison and billing behavior](free-hosting-comparison.md).

Use a dedicated Hobby workspace without a payment method for a zero-spend
prototype if its account permits that. Confirm the selected service is Free,
remaining allowances and any account-specific eligibility requirement. If a card
is already attached, overages can incur charges. A build-pipeline spend limit
does not establish a universal spending cap. Do not automatically upgrade.
No credit-card information or actual billing setting was inspected here.

Neon's previously verified Free allowances and sleep behavior remain in the
[comparison](free-hosting-comparison.md). Recheck the selected account, region,
PostgreSQL version, endpoint and TLS configuration before
connecting. The application uses individual database fields, not `DATABASE_URL`;
enter them through secure settings rather than printing an authenticated URL.

Use the **direct Neon endpoint initially** for this small single-worker candidate,
and always for migration and `pg_dump`/`pg_restore`. Neon documents its pooled
endpoint as PgBouncer transaction pooling, with session-feature restrictions;
the Console's connection-pooling toggle is on by default for new projects.
Do not accidentally use its `-pooler` hostname for operator tasks. The current
app uses `CONN_MAX_AGE=0`; evaluate pooling separately if measured connection
volume justifies it, with actual shared-quota/ledger concurrency checks.

## Settings and controlled release

Use the blueprint's `sync: false` entries and
[production environment template](../deploy/production.env.example) as the list
of secure settings. Keep an explicit service hostname and a strong persistent
application secret. The Intrinio vault binding in this development environment
does not provision Render credentials; a proxy placeholder must not be copied.
No credential values belong in chat, Git or build commands.

`DJANGO_DATABASE_SSLMODE=verify-full` is mandatory. Supply a trusted CA path
readable on the target through `DJANGO_DATABASE_SSLROOTCERT`, or confirm the
client's system-root mechanism is supported before selecting it. Neon's official
secure-connection source lists `/etc/ssl/certs/ca-certificates.crt` for Debian/Ubuntu
clients; verify that path exists on the chosen runtime before using it. A connection
with `sslmode=require` alone is insufficient. Do not copy this environment's
session proxy certificate to an unrelated production host. Verify the actual
host certificate and database hostname with the intended client before migration.

Keep `DJANGO_TRUST_PROXY_HTTPS=false` until Render's ingress is confirmed to
replace `X-Forwarded-Proto` and block direct external application access. Then
review an explicit switch to true and test real HTTPS, hostile headers and
redirects. The false value is safe for a draft but cannot make authenticated
pages usable behind HTTP-to-app TLS termination: it will redirect them again.
Process liveness alone cannot detect this mistake.

No production migration or user creation occurs during build or worker startup.
Render Free explicitly provides **no shell/SSH or one-off jobs**. Use a trusted
operator machine with the locked checkout, the direct database endpoint and
securely loaded production settings for the initial release. These are operator commands,
not commands executed against any hosted database in this task:

```sh
uv sync --frozen --no-dev
uv run --frozen --no-dev python manage.py check --deploy
uv run --frozen --no-dev python manage.py migrate --plan
# After confirming the intended database, schema change and required backup:
uv run --frozen --no-dev python manage.py migrate --noinput
uv run --frozen --no-dev python manage.py createsuperuser
```

Supply credentials through the operator's secure environment, not shell argv.
Use the intended migration role and verify runtime role grants separately;
do not give the running web application provider-admin credentials. The built-in
user command prompts for its password. An application superuser is distinct from
a PostgreSQL superuser. These commands create neither fixtures nor provider data.
Freeze application writes during any later incompatible migration and take a
verified backup first; never race a schema change against active workers.

The code currently exists as local changes. Git-based hosting will require an
authorized source commit/push or other supported upload before it can build
this release. Do not connect Render to the old remote README and claim the
application is deployed. After reviewing terms, account access, data rights and
the concrete configuration, authorize the selected external release separately.

## Backups and acceptance

Web-local files are not durable portfolio storage. Use PostgreSQL for account,
journal and watchlist records. The process-only probe deliberately avoids
database traffic that would prevent Neon from suspending. Do not create a
keep-awake service to defeat free-tier sleep.

Render's frequent health probes accept 2xx/3xx within five seconds and use the
service hostname (or a verified custom domain) as `Host`. Include that hostname
in `DJANGO_ALLOWED_HOSTS`. The endpoint remains process-only, so it deliberately
does not satisfy Render's optional suggestion to query the database on each probe.
A busy single synchronous worker can delay probes; measure normal research
requests on the actual low-CPU instance before accepting reliability. No local
smoke establishes peak memory or timing on Render's Free compute.

The existing [backup command and restore drill](backups.md) are implemented.
An encrypted off-machine destination, scheduler, retention and matching native
PostgreSQL client tools still need selection and a real-target recovery drill.
Do not declare a paid cron job or persistent disk to solve this without approval.
For a personal prototype, an existing trusted computer can run backups on a
schedule, but its availability and encrypted copy location must be established.
Neon's short restore history does not replace those copies.

Before opening access, verify hosted HTTPS/sign-in, anonymous research denial,
closed registration, static assets, owner isolation, real database TLS, quotas,
bounded Intrinio requests under applicable subscription rights and restoration
into an isolated database. Local runtime checks do not prove these hosted results.

## Evidence and next action

Current application evidence remains 995 PostgreSQL tests passing from the prior
release. This draft adds no application feature or dependency; the full suite was
not repeated for it. The new build script passes both fresh and repeated builds
with synthetic production settings, no provider key and an unused loopback
database endpoint. Its separate runtime environment contains 23 locked packages.
Actual two-worker Gunicorn/WhiteNoise smoke passes using those fresh packages;
owned smoke processes stop. The two existing intentional HSTS advisories remain
printed, with no checks silenced. Shell syntax, Ruff (215 files), frozen development
setup (24 packages), local migrations/no drift and fresh normal startup/readiness
also pass. All seven development business/counter counts remain zero and the
original specification checksum is unchanged. These results do not validate
the actual Render deployment, ingress, account allowances or hosted database.
The updated review template separately passes the current official public schema.

Next: establish the Free Render/Neon accounts and secure access needed for this
prototype, then review the concrete external release. The remaining work covers
account setup, source publication, database/TLS, the first user, backup scheduling
and hosted acceptance; it is more than pressing a deploy button.

Sources checked: [Render Free](https://render.com/docs/free),
[pricing](https://render.com/pricing),
[Blueprint reference](https://render.com/docs/blueprint-spec),
[schema](https://render.com/schema/render.yaml.json),
[Python version](https://render.com/docs/python-version),
[web-service ingress](https://render.com/docs/web-services),
[health checks](https://render.com/docs/health-checks),
[Neon TLS source](https://github.com/neondatabase/website/blob/main/content/docs/connect/connect-securely.md)
and [Neon pooling source](https://github.com/neondatabase/website/blob/main/content/docs/connect/connection-pooling.md).
