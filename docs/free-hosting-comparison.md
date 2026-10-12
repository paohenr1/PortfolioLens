# Free hosting comparison

Verification update, October 12, 2026. The application remains version 0.31.0. The
user asked to compare free options before selecting a host. No account, hosting
resource, subscription, public endpoint or paid service was created.

## Recommendation

Shortlist **Render Free for the Python web process plus Neon Free for PostgreSQL**
for a small personal prototype. This targets zero additional hosting fees while
staying within both providers' free allowances; existing Intrinio subscription
charges are separate. Render's current public limits are now verified below.
Render explicitly advises against Free for production applications. This is a
personal prototype candidate with cold starts and possible suspension, not a
reliable always-available release. Account eligibility, usage and actual hosted
behavior still need verification before provisioning.

Use Neon as the database rather than placing portfolio/journal records on a web
process's local filesystem. Our production configuration requires PostgreSQL
with password authentication and verified TLS, shared quota rows and persistent
relational storage. A free web process does not establish durable database storage.
Render's own Free database expires after 30 days, has no backups and is deleted
after a further 14-day grace period if not upgraded. Do not use it for this app's
ongoing portfolio records.

For reliable always-available use, evaluate a small paid service or existing
server separately. No reviewed free offer establishes that reliability for this
app. Do not promise permanent free hosting or introduce charges automatically.

## Comparison

| Option | Confirmed free offer | Fit and limitations for this app |
| --- | --- | --- |
| Render web + Neon database | Render Free web: 512 MB RAM, 750 workspace service-hours/month; Hobby includes 5 GB bandwidth and 500 build minutes. Neon lists $0/month within its Free allowances. | Personal prototype candidate. Render sleeps after 15 idle minutes with about a one-minute wake-up; heavy external traffic can trigger suspension. No free shell/one-off jobs. Avoid payment-backed overages and use independent backups. |
| Railway + PostgreSQL | $0 Free plan includes **$1 resource credit/month**; Free service ceiling is 0.5 GB RAM and 1 vCPU. | Suitable for small experiments, not a demonstrated zero-cost continuously running app/database. Resources consume credit. Hobby starts at $5/month with $5 included usage; do not select it without authorization. |
| Fly.io | Trial is **2 total VM hours or 7 days**, whichever is reached first; trial machines automatically stop after five minutes. | A deployment trial, not ongoing free hosting for this platform. Adding a payment method ends the trial and starts billable usage. |
| Existing personal computer | No new hosting subscription if suitable hardware already exists. | Keeps local PostgreSQL and personal access under the owner's control. Requires installation, backups and keeping the computer running; does not provide a managed hosted URL or internet reliability. |

Railway's published RAM rate is $10/GB-month, before CPU/storage/egress. An
illustrative 0.1 GB average RAM alone uses $1/month; this is arithmetic from its
rate, not a measurement of this app's memory. Its credit should not be interpreted
as enough to host the complete application indefinitely.

## Verified Neon Free limits

The provider's official plans source, updated October 6, 2026, currently states:

- **1 GB PostgreSQL storage per project**, with 20 GB across the account.
- **100 compute-unit hours per project per month** and **5 GB public transfer**.
- Database compute suspends after **five idle minutes**; Free cannot disable this.
- Instant restore history is up to **six hours**, capped at 1 GB of changes,
  plus one manual snapshot. This does not replace independent backup copies.
- Exhausting compute/transfer suspends compute until the next period or upgrade.
  Exceeding storage limits makes storage-increasing operations fail; the source
  says these limits do not delete data.

Keeping a 0.25-compute-unit database active all the time would exceed 100
compute-unit hours in a typical month. Readiness probes that repeatedly query
the database can defeat idle suspension. Future deployment health checks should
separate process liveness from occasional database readiness and should not
use artificial traffic to keep a free service awake. Actual usage must be measured.

## Verified Render Free limits and spending behavior

Official Free, pricing, Blueprint, bandwidth and build-pipeline pages were read
successfully on October 12, 2026 through the configured HTTPS proxy:

- Web compute is **512 MB RAM**; the Blueprint reference lists **0.1 CPU**.
  **750 Free instance hours per workspace/calendar month** are shared across free
  web services. Sleeping services use no instance hours. Exhaustion suspends free
  services until the next month.
- A service sleeps after **15 idle minutes** and wakes on a request in about
  **one minute**. Render can restart it at any time. Local filesystem changes
  disappear on sleep/restart/redeploy; Free supports no persistent disks.
- Hobby workspaces include **5 GB outbound bandwidth** and **500 Starter build
  pipeline minutes/month**. External database/API traffic counts as outbound
  usage. Uncommonly high service-initiated internet traffic can cause suspension;
  Render gives no numeric threshold on the Free page. That matters for Neon and
  Intrinio even if ordinary browser traffic is small.
- With a payment method, bandwidth/build overages can purchase supplementary
  usage. Without one, excess bandwidth suspends free services and exhausted build
  minutes stop new builds for the month. A pipeline spend limit is specifically
  a **pipeline** control, not a verified cap on all bandwidth/compute charges.
  Prefer a separate Hobby workspace without a payment method for a zero-spend
  prototype, if the account permits it. Confirm its actual billing settings.
- Free has **no shell/SSH, one-off jobs, multi-instance scaling or persistent
  disk**. Run controlled migrations, initial user provisioning and native backups
  from a trusted operator machine, not an assumed free job on Render.
- Render Free Postgres is **1 GB**, expires after **30 days**, and is deleted
  after a **14-day upgrade grace period**. It provides no backups. The draft
  intentionally declares no Render database.

The [deployment template](../deploy/render.yaml.template) passes the current
official Render schema, uses `autoDeployTrigger: "off"`, and disables automatic
preview services. No resource was created. Public documentation does not prove
eligibility or limits remaining on a particular account.

## Before deployment

Choose a candidate after verifying its current terms. Then prepare and test the
host-specific build/start commands, Python/static serving, HTTPS and trusted
ingress, database role/TLS configuration, migrations and encrypted off-machine
backup/recovery procedure. Keep private records out of ephemeral web storage.
Use the existing Intrinio feed and confirm its applicable personal-use,
display/storage and access terms before exposing research data through a hosted
app. Do not assume an individual subscription permits public redistribution.

Current research pages and registration are public in the development app;
owner isolation protects portfolios/watchlists. A hosted personal deployment
still needs a reviewed access policy before opening the site to others. Hosted
private access, account creation, provider credentials and data rights have not
been established by this comparison.

Keep Free plans explicit and avoid automatic paid upgrades. Select compatible
web/database regions where possible. Review cold-start behavior, storage/compute
limits and backup retention on the actual account. This comparison does not
create a hosting account or authorize a billable resource.

## Sources and verification

The initial comparison used official provider source repositories through the
permitted GitHub route. Render's live documentation and pricing are now accessible
after the supported domain changes were applied; no proxy/TLS bypass occurred.
Neon, Railway and Fly findings remain dated source checks, not account-level
verification. Sources can change after this comparison.

- [Neon plans source](https://github.com/neondatabase/website/blob/main/content/docs/introduction/plans.md)
  and [published plans](https://neon.com/docs/introduction/plans).
- [Railway pricing source](https://github.com/railwayapp/docs/blob/main/content/docs/pricing/plans.md)
  and [published plans](https://docs.railway.com/pricing/plans).
- [Fly.io trial source](https://github.com/superfly/docs/blob/main/about/free-trial.mdx)
  and [published trial](https://docs.fly.io/about/free-trial/).
- [Render's official Django blueprint](https://github.com/render-examples/django/blob/main/render.yaml)
  and [verified Free documentation](https://render.com/docs/free),
  [pricing](https://render.com/pricing),
  [outbound bandwidth](https://render.com/docs/outbound-bandwidth),
  [pipeline allowances and spend limit](https://render.com/docs/build-pipeline),
  [Blueprint reference](https://render.com/docs/blueprint-spec) and
  [official schema](https://render.com/schema/render.yaml.json).

The existing frozen environment, local PostgreSQL/migrations and normal startup
remain the development workflow. The v0.31 [private serving package](production-serving.md)
and [deployment draft](render-deployment.md) are implemented and locally tested.
Render Free terms and the blueprint's schema are now checked; hosting accounts,
actual ingress/database TLS, source publication, backups, rights and hosted
acceptance remain unverified. No hosting resource or charge occurred.
