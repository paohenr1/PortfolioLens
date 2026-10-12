# Development setup and testing

The current version is 0.31.0, including [production serving/private access](production-serving.md).
Current verification: 995 PostgreSQL tests passed; SQLite passed 703 and skipped
292 PostgreSQL-only cases. Dated feature sections below retain earlier results;
the final v0.31 section records the latest checks.

These instructions prepare the foundation, stock search/reference, daily-price charts,
company financial statements, user accounts, and private portfolio metadata.
The adapter is implemented and fixture-tested. Live Intrinio search/reference
and browser selection passed on October 10, 2026 with the vault-bound cloud key.
Daily-price retrieval and raw/adjusted charts also passed live one-year AAPL
browser verification. Income, balance-sheet, and cash-flow statements also
passed authenticated browser checks for AAPL fiscal 2025 FY. Accounts and
private portfolio creation/list/details also pass desktop/mobile browser checks.
The append-only USD journal records cash movements, trades, and fees. FIFO
positions, cost basis, and realized sale gains are implemented. Explicit-date
market valuations and unrealized gains, cash-inclusive allocations, time-weighted
returns, daily session series, private watchlists and explicit journal corrections are implemented.
Production deployment remains pending. Explicit
net dividends and exact forward/reverse splits are now implemented.

## Prerequisites and installation

Use Python 3.12 and uv (the validated cloud tool version is 0.12.19). The project
does not require Node.js or a new paid service. Private portfolios require
PostgreSQL; the local Docker helper is documented in [portfolio setup](portfolios.md). An Intrinio key
is required for successful live search, not for startup or fixture-based tests.
Obtain uv through its official installation instructions if it is not already
available; CI installs the pinned version from PyPI.

In the cloud, the repository directory is
`/workspace/Stock-Research-Portfolio-Analytics-Platform`. Run all commands below
from that directory, or your existing local checkout's root. Each cloud task is
already isolated; use the existing checkout and do not create a Git worktree
unless the user explicitly requests one.

```sh
uv sync --frozen
uv run --frozen python manage.py migrate --noinput
uv run --frozen python manage.py check
```

The frozen installation uses `uv.lock`, including artifact hashes. Do not
disable TLS or checksum verification. The initial database is the ignored
`db.sqlite3`; migrations are safe to repeat. `.venv`, local databases, caches,
logs, environment files, and collected assets are ignored.

The cloud's writable cache location can be selected with:

```sh
export UV_CACHE_DIR=/workspace/.cache/uv
```

## Start the development application

```sh
uv run --frozen python manage.py runserver 127.0.0.1:8006 --noreload
```

Use loopback binding for this local development server. The landing page should
return HTTP 200, offer stock search, and, without a key, show:

> Market data unavailable: Intrinio is not configured.

The local stylesheet at `/static/research/site.css` must also return HTTP 200.
The empty `/search/` form returns HTTP 200 without contacting Intrinio. A
submitted search with no key returns HTTP 503 and the explicit unavailable
message. Version 0.16 was validated on port 8004 with a fresh server; earlier
milestones used ports 8003, 8002 and 8001. Occupied ports without established
process ownership are left alone. After managed terminal cancellation left the process running, exact commands,
UID and checkout were inspected outside the command sandbox. Only the two
servers started in this turn were terminated; the normal app was restarted on
8004 and rechecked successfully. Verify routes after startup rather than assuming an
existing process has loaded the latest code.
The chart script at `/static/research/prices.js` also returns HTTP 200. Opening
`/stocks/<security_id>/prices/` shows date/basis controls without requesting data;
submitting a valid date range requests up to four pages of historical prices.
Opening `/stocks/<security_id>/financials/` also shows its form without provider
calls. A valid statement/year/period submission uses up to three requests.
A running process or open port alone does not prove this page works. Cloud
onboarding does not support public previews of loopback addresses; use local
requests for verification rather than publishing localhost links.

Development server processes must restart in a new cloud task. In managed
execution tools, retain the session handle for logs. Terminal cancellation can
leave a child process running. If the sandbox hides process IDs, inspect them
through the supported outside-sandbox tool, verify exact command/UID/checkout,
and stop only the process you started before restart. Never reuse saved PIDs.
If ownership cannot be established, choose a free port and update readiness
requests consistently. The source,
virtual environment, and local files can be retained; do not assume a running
server survives a snapshot. The saved environment `start_skill` contains the
working directory, startup steps, and these readiness expectations.

## Environment variable reference

| Variable | Development behavior | Production configuration |
| --- | --- | --- |
| `DJANGO_ENV` | Defaults to `development` | Explicitly set `production` |
| `DJANGO_DEBUG` | Defaults to true; accepts true/false/1/0 | Defaults false; true is rejected |
| `DJANGO_SECRET_KEY` | Optional; generated per process if absent | Required: at least 50 characters, at least 5 distinct characters, no `django-insecure-` prefix |
| `DJANGO_ALLOWED_HOSTS` | Defaults to localhost, 127.0.0.1, [::1] | Required explicit hostnames/IPs; no wildcard, scheme, port, or path |
| `INTRINIO_API_KEY` | Optional for startup; required for provider search/reference/prices/statements | Configure securely for backend requests only |

Generate production keys with a cryptographically secure generator. Validation
checks are guardrails, not proof of entropy. No reusable key is embedded in
source. For development, a generated per-process key means sessions will not
survive a restart unless a stable local key is provided.

Django does not automatically read `.env`. To use local values, copy
`.env.example` to `.env` only if `.env` does not already exist, edit it locally,
then run:

```sh
uv run --frozen --env-file .env python manage.py check
uv run --frozen --env-file .env python manage.py runserver 127.0.0.1:8004 --noreload
```

Never overwrite an existing environment file blindly. Keep secret values out
of chat, source control, test fixtures, logs, and saved setup instructions. Use
secure environment settings for cloud credentials. Existing proxy-backed
bindings are used through the platform's supported HTTPS proxy route. Restart
the development server after changing its environment bindings.

A present key changes the message to:

> Intrinio credentials are configured; data access is checked when you search.

That message does not claim authentication or dataset access. Submitting search
or selecting an instrument triggers one bounded backend request. No fixture
data is displayed by normal startup. Historical-price pages request data only
after submission; each pagination request spends the shared quota.
Statement submissions reserve quota separately for security resolution,
period lookup, and financial values. See [Intrinio integration](intrinio.md),
[price history](price-history.md), and [fundamentals](fundamentals.md).

## Automated checks

Prepare local PostgreSQL with `python3 scripts/development_database.py` before
running the full suite. The test-role environment file isolates development
data. These files are generated locally and ignored by Git.

```sh
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen python manage.py check
uv run --frozen python manage.py makemigrations --check --dry-run
uv run --frozen --env-file .local/database-test.env python manage.py test --verbosity 2
uv run --frozen python manage.py collectstatic --noinput
```

The 995 tests cover configuration validation, actual Django startup failures,
production cookie/HTTPS settings, credential redaction, missing and configured
provider states, unsafe request methods, untrusted hosts, security headers, and
password hashing/authentication through the custom user model. Added tests
exercise provider normalization, malformed responses, authentication and
entitlement errors, timeouts, rate limits, redirects, safe logs and HTML,
concurrent request budgets, search-to-selection integration, and the live-check
command's failure/success semantics. Price tests cover exact decimal parsing,
date and page bounds, pagination/cursor failures, identity/currency consistency,
missing/zero values, partial/unconfirmed periods, gap segmentation, calendar
spacing, shared quotas, safe errors, and the price-verification command.
Statement tests cover company identity, explicit period selection, the verified
balance-sheet endpoint code, reported/calculated/restated classifications,
date/time precision, exact negative/zero/missing values, unit preservation,
partial responses, per-stage failures/quotas, escaping/redaction, and acceptance
commands. Account tests cover registration/password validation, current-user
isolation, CSRF, safe redirects, session rotation, password changes across
sessions, inactive users, private cache/cookie settings, and concurrent attempt
limits. The database
tests use an isolated PostgreSQL test database for the full suite, not the
development database. SQLite runs skip 292 PostgreSQL-only persistence/admission tests;
the selected foundation/guard suite also passes separately. Added database and
portfolio tests cover TLS/configuration, owner isolation, forged owner IDs,
constraints, pagination, CSRF, escaping, and concurrent name/allowance enforcement.
Ledger checks cover exact rounding, historical cash/share reconciliation,
duplicate-submit keys, immutable rows, the entry cap, and concurrent appends.

`collectstatic` verifies that the application assets can be collected. It is
not a production static-file server or a deployment check.

The GitHub Actions workflow runs these commands with pinned action commits,
Python 3.12, and a frozen dependency install. Remote GitHub Actions execution
has not been observed; the commands have been run in the cloud workspace.
The foundation does not yet include a dedicated type checker, dependency
vulnerability scanner, or secret scanner; add those as the workflow expands.

## Browser verification

The environment's existing Playwright and Chromium were used at 1280×900 and
390×844. The test-only workflow searches, selects an instrument, checks its
reference details, loads adjusted prices, inspects chart points, and opens the
table with the keyboard. Empty results, search authentication/rate-limit failures,
and a price rate-limit page are checked. Layout overflow, local CSS loading,
and unexpected JavaScript/external
page requests are checked. Mobile screenshots were also inspected.

Run this optional smoke check with the cloud's system Python, which supplies
Playwright, and an existing `.venv` from `uv sync --frozen`:

```sh
python3 tests/browser_smoke.py
python3 tests/browser_fundamentals.py
python3 tests/browser_authentication.py
python3 tests/browser_portfolios.py
python3 tests/browser_ledger.py
python3 tests/browser_fifo.py
python3 tests/browser_actions.py
python3 tests/browser_valuation.py
python3 tests/browser_performance.py
```

The runner starts a separate loopback-only fixture server on an OS-assigned
port and stops it afterward. It uses `/usr/bin/chromium`, saves test screenshots
under `/tmp/stock-search-*` and `/tmp/stock-prices-*`, and preserves server diagnostics at
`/tmp/stock-search-fixture-server.log`. It is not a production fixture mode.
No new browser dependency was added to the application. Other machines need
Playwright/Chromium separately; this optional check is not yet in GitHub Actions.
Live search and instrument selection also passed in a separate browser check
against the normal application. Live one-year raw/adjusted charts, point
inspection, and the table also passed with 251 completed AAPL observations.
Desktop/mobile price layouts passed. The separate PostgreSQL portfolio runner
passes two-user create/list/detail, foreign-owner 404, duplicate-name validation,
sign-out, and desktop/mobile keyboard checks using a disposable database.
The fundamentals runner starts fresh test-only processes for each statement
type, staying inside the real request budget. It checks search-to-statement
workflows, metrics and keyboard-accessible tables, desktop/mobile layouts, and
missing/empty/entitlement/rate-limit states. Screenshots are under
`/tmp/stock-financials-*`; diagnostics are in
`/tmp/stock-fundamentals-fixture-server.log`. A separate authenticated browser
check passed AAPL 2025 FY income (22 rows), balance-sheet (30 rows), and cash-flow
(22 rows) pages. The balance sheet was correctly labeled restated.

## Module map and limitations

- `config/environment.py`: validated environment configuration with redacted
  representations and value-free error messages.
- `config/settings.py`: Django framework settings and initial security policy.
- `config/middleware.py`: browser content restrictions for locally served assets.
- `accounts/models.py` and its migration: initial extensible Django user model.
- `market_data/`: typed contracts, Intrinio transport, normalization, safe errors,
  credential redaction, and configuration status.
- `market_data/prices.py`: date-range bounds and strict daily-close normalization.
- `market_data/fundamentals.py`: statement/period, metadata, and numeric-value validation.
- `ledger/fifo.py`: pure FIFO allocation and gain calculations; `ledger/analytics.py`
  reads a bounded owner-scoped snapshot without quotes or persisted totals.
- `ledger/valuation.py`: pure date-matched USD valuation; `ledger/valuation_services.py`
  explicitly loads bounded raw daily closes, leaving incomplete totals unavailable.
- `ledger/allocations.py`: pure cash-inclusive weights with reconciled percentage rounding.
- `ledger/performance.py`: pure EOD cash-flow plan and exact linked returns;
  separate services/forms/views provide bounded, private explicit loading.
- `research/charts.py`: pure Python chart coordinates and exact-price presentation.
- `research/fundamentals.py`: pure statement/metric presentation and provider-unit labels.
- `research/forms.py` and `services.py`: query validation and bounded request orchestration.
- `research/views.py`, templates, and static assets: home, search, reference, price, and financials pages.
- `tests/`: framework, transport, user, search, failure, budget, and browser tests.

Production mode enforces HTTPS redirects and secure cookies, but deployment is
not complete. A production WSGI/ASGI server, verified proxy handling, a production PostgreSQL service,
static-file serving, operational logging policies, backup/restore, shared request limits,
and full deployment checks remain future work. HSTS is initially short and
does not opt into preload or all subdomains before domain ownership and HTTPS
have been validated. Do not deploy using Django's development server.

The current cloud environment has a working secure key binding and network
access to `api-v2.intrinio.com`; search/reference and bounded AAPL price access
and AAPL 2025 annual statement access are verified. Future environments still
require those settings. Other instruments/periods, datasets, account quotas, and
licensing require separate verification before claiming those datasets or
exposing the application publicly.

## Account readiness

The empty `/register/` and `/sign-in/` forms return HTTP 200 without provider
requests. A signed-out `/account/` request redirects to `/sign-in/?next=/account/`.
Registration, sign-in/out, password changes, and a current-user-only account
page are implemented. Password recovery is unavailable. The optional account
browser runner uses a temporary database and removes its two test accounts
with that database; it never writes to the development database. It checks
desktop/mobile layouts, validation, sign-out, and password-change/re-login.
See [accounts and authorization](authentication.md) for limits and production
requirements. Private USD portfolio metadata is now implemented on PostgreSQL;
see [portfolio setup](portfolios.md) and [transaction journal](ledger.md).
The append-only USD ledger and [FIFO positions/gains](fifo.md) are implemented.
Recorded [dividends and splits](corporate-actions.md) are implemented.
Explicit-date [market valuation and unrealized gains](valuation.md) are implemented.
[Allocation weights](allocations.md) reuse complete valuations without new requests.
[Time-weighted performance](performance.md) now supports confirmed end-of-day flows.
Private [watchlists](watchlists.md) and [journal corrections](corrections.md) are implemented. Bounded [daily session returns](daily-returns.md) are implemented. Observed [volatility and drawdown](risk.md) are implemented. Benchmark comparison is next.

## Private portfolio readiness

For the full local workflow, run the database helper, migrate with
`--env-file .local/database.env`, and start Django with the same file. SQLite
startup remains supported for research/accounts, with explicit portfolio
unavailability. A signed-out `/portfolios/` request redirects to sign-in and
creates no records. Empty portfolio forms and pages make no Intrinio calls.
The database helper, full test command, CI service configuration, production
TLS settings, role separation, and limits are documented in
[private portfolios and PostgreSQL](portfolios.md).

## Transaction journal readiness

The private USD journal requires the same PostgreSQL settings and all three ledger
migrations, including the update/delete rejection trigger. Open a portfolio
and choose **View transactions**. Cash events use no provider requests; a new
trade resolves its instrument ID once through Intrinio and uses the manually
entered execution price. Entries are permanent; explicit audited corrections are now implemented. Explicit dividends and splits are now
implemented; see [corporate actions](corporate-actions.md). See [ledger rules and verification](ledger.md).
The optional browser ledger runner enables synthetic reference data only in
its separate temporary PostgreSQL test server; normal startup never does.

## FIFO positions readiness

Portfolio details and transaction history link to **View positions and gains**.
The GET-only page derives cash, open basis, realized sales, and lot provenance
from the bounded journal, with independent 25-row table pagination. No new
migration or provider access is needed for calculations. Signed-out UUID
position URLs redirect to sign-in without writes. See [FIFO rules](fifo.md)
for fee allocation, cumulative half-up cents, examples, and browser verification.

## Recorded corporate actions

Apply ledger migration 0003 before recording Dividend or Split entries. The
existing private journal form provides net cash received and new-for-old split
terms. No action feed is automatically requested. Split conversions must be
exact at six share decimals for each open FIFO lot; unsupported fractions and
cash-in-lieu are rejected before reference lookup and again inside the lock.
Read [action rules and upgrade verification](corporate-actions.md) before entry.

## Market valuation readiness

Choose **View market valuation** from portfolio details, history, or positions.
GET opens only the form. A CSRF-protected submission selects a completed date
and explicitly checks recorded share basis, then makes at most one price request
for each of up to five open instruments. Cash, FIFO cost, holdings and confirmed
raw closes all use that exact date; missing prices leave totals unavailable.
Read [valuation rules and limits](valuation.md). The optional synthetic browser
runner `python3 tests/browser_valuation.py` uses its own generated PostgreSQL
database and cleans up its child/database; normal startup never enables fixtures.
Full PostgreSQL: 739 passed; full SQLite: 484 passed, 255 skipped. Valuation,
FIFO and action desktop/mobile browser checks passed. Current-instance startup
forms, private redirects and assets pass without API requests or created records.

## Allocation readiness

The same **Load valuation** submission shows an allocation table for recorded
cash and each open instrument. The denominator is cash plus complete position
market value from that same date-scoped snapshot. Missing prices withhold every
weight; a zero total gives an explicit unavailable state. Reconciled two-decimal
percentages sum to 100.00%, including cash. There are no extra provider calls,
database writes, routes, dependencies or migrations. See [allocation rules](allocations.md).
The expanded `tests/browser_valuation.py` checks normal, cash-only, empty and
incomplete allocations with desktop/mobile tables and owner/CSRF protections.

## Time-weighted return readiness

Choose **View time-weighted returns** on portfolio details, history, positions,
or valuation. GET makes no price request. A CSRF-protected POST selects completed
opening/closing dates and requires confirmed end-of-day cash-flow/share-basis timing.
The same materialized journal snapshot produces every boundary's cash and holdings.
External flows after the opening date must follow all other same-day activity.
No more than eight price requests, five holdings per boundary and 16 boundary dates
are supported. Missing boundary prices withhold the full return; zero opening
values are undefined. No database migration or new dependency is needed.
Read [definitions and verification](performance.md). `tests/browser_performance.py`
uses an isolated PostgreSQL database and synthetic prices, then cleans up its child/DB.
Full PostgreSQL: 739 passed; full SQLite: 484 passed, 255 skipped. Performance,
valuation/allocation and FIFO desktop/mobile browser workflows passed.

## Private watchlist readiness

Apply `watchlists/0001_initial` with the same PostgreSQL settings, then open
**My watchlists**. Create a list and use **Add to watchlist** from instrument
details or enter its stable ID through a list's **Add instrument** form. A new
bookmark uses one bounded reference request; list/forms, duplicate retries and
confirmed removals make none. Foreign/missing IDs use generic no-store 404s.
SQLite explicitly returns storage unavailable. Read [watchlist rules](watchlists.md).
`python3 tests/browser_watchlists.py` uses an owned temporary PostgreSQL database
and synthetic transport, then cleans up its child/database. Full PostgreSQL:
739 passed; full SQLite: 484 passed, 255 skipped. Current-instance private
watchlist redirects, research/account forms and assets pass without records or
provider calls. No new dependency, paid service or live API check was added.

## Correction readiness

Apply ledger migrations 0004 and 0005 with the normal development database
settings. Current transactions have **Correct** and **Void** controls, with
read-only preview, signed 15-minute intent, explicit confirmation, permanent
audit and a full-journal recheck. Corrections restate event-date calculations;
original entries remain immutable. Read [correction rules](corrections.md).
`python3 tests/browser_corrections.py` uses a generated PostgreSQL database and
explicit synthetic transport, then removes its child/database. Full PostgreSQL:
739 passed; SQLite: 484 passed, 255 skipped. Correction, performance,
valuation/allocation and watchlist browser workflows pass. No new dependency,
paid service, live API call or development record was added.


## Daily session returns — version 0.15

Open **View daily returns** on an owned portfolio. The form loads no prices until
a confirmed POST. Choose completed U.S. equity session dates from 2000, at most
90 calendar days apart inclusively. A maintained NYSE calendar supplies the
consecutive session grid; the opening close is the baseline. Missing required
closes withhold adjacent returns and the complete-period result.

The service reads one effective corrected journal snapshot, includes holdings
sold within the period, and bounds loading to two instruments/four pages each.
Every page shares the existing provider budget. Cash-only series make no price
requests. Non-session activity and unsupported intraday flow order are rejected
before requests; the existing 16 cash-flow boundary limit applies.

`exchange-calendars==4.13.2` is a free Python dependency locked with hashes. Its
NumPy/pandas/calendar/time-zone dependencies support session determination;
financial money and return calculations continue to use Decimal/Fraction. No
paid service, new network destination, database migration or live API call was
added. Updating this calendar requires checking holiday/exceptional closure tests.

```sh
uv sync --frozen
uv run --frozen --env-file .local/database-test.env python manage.py test --noinput
python3 tests/browser_daily_returns.py
```

Full PostgreSQL: 739 passed without skips. SQLite: 484 passed, 255 skipped. The
daily return browser passes desktop/mobile with synthetic data in its disposable
PostgreSQL database; the correction and performance browsers also pass. Ruff,
Django checks, migration drift and static collection pass. See
[daily return definitions, limits and validation](daily-returns.md). Observed [volatility/drawdown](risk.md) are implemented; [benchmark comparisons](benchmarks.md) are implemented; live portfolio-series acceptance remains unverified.


## Volatility and drawdown — version 0.16

The existing private daily-return POST now also calculates observed risk. Daily
sample volatility needs two complete returns; annualized volatility needs twenty
and scales unrounded sample variance by 252. Drawdown removes external cash
flows and shows the worst episode's peak, trough and first recovery. An incomplete
series withholds all risk metrics and its chart; valid rows are never discarded.

The pure calculation module imports without Django initialization. A separate
SVG presentation module and the existing local price-chart script provide a
responsive chart and full table, with pointer and keyboard controls. No dependency,
migration, provider request or database write is added by calculating risk.

```sh
python3 tests/browser_risk.py
python3 tests/browser_daily_returns.py
python3 tests/browser_smoke.py
```

Full PostgreSQL: 739 passed without skips. SQLite: 484 passed, 255 skipped.
Risk/daily and existing price-chart browser checks pass with synthetic data on
desktop/mobile. Ruff checks 158 Python files; Django, migration drift and static
checks pass. See [risk definitions and validation](risk.md). Live portfolio-risk
acceptance remains unverified; [benchmark comparisons](benchmarks.md) are implemented; [correlation and beta](relationships.md) are implemented; [Sharpe](sharpe.md) is implemented; [Selected-period profitability](profitability.md) is implemented; [annual return on assets/equity](capital-returns.md) is implemented; [annual revenue and earnings growth](growth.md) is implemented; valuation multiples with explicit dates are next.


## Benchmark comparison module

Version 0.17 adds an optional security ID to the confirmed daily-return form.
Its adjusted-price proxy uses every portfolio session, exact linked returns and
percentage-point gaps, with a chart and accessible values table. One benchmark
reference and at most one price page bring the action ceiling to ten requests;
same-instrument histories are reused. Blank selection requests nothing extra.
Provider adjustment/index methodology remains unverified. See
[benchmark definitions, bounds and limitations](benchmarks.md).

```sh
uv sync --frozen
python3 scripts/development_database.py
uv run --frozen --env-file .local/database.env python manage.py migrate --noinput
uv run --frozen --env-file .local/database-test.env python manage.py test --noinput
python3 tests/browser_benchmarks.py
```

Full PostgreSQL: 739 passed, no skips. SQLite: 484 passed, 255 skipped.
Benchmark, daily, risk and existing price-chart browsers pass desktop/mobile
with synthetic data only. Ruff checks 142 files; Django, migration drift and
static collection pass. The restored local database was started with the existing
helper, and the application was freshly started on the available port 8004;
HTTP readiness checks passed without provider requests. Development portfolio
and journal data remain empty, and browser databases are removed after checks.
No dependency, migration, paid service or live API request was added.
[Correlation and beta](relationships.md) are implemented. [Sharpe](sharpe.md) is implemented. [Selected-period profitability](profitability.md) is implemented. [Annual return on assets/equity](capital-returns.md) is implemented. [Annual revenue and earnings growth](growth.md) is implemented. Next: valuation multiples with explicit price and earnings dates.


## Correlation and beta module

Version 0.18 reuses the exact paired benchmark/portfolio session factors to show
Pearson correlation and OLS beta with an intercept. Both require twenty complete
returns. Zero benchmark variance withholds both; a constant portfolio has zero
beta and unavailable correlation against a varying benchmark. Incomplete series
withhold both without dropping sessions. Calculations add no provider requests,
storage writes, dependency, migration or paid service. See
[relationship definitions and exact rounding](relationships.md).

```sh
uv run --frozen --env-file .local/database-test.env python manage.py test --noinput
python3 tests/browser_relationships.py
python3 tests/browser_benchmarks.py
```

Full PostgreSQL: 739 passed with no skips. SQLite: 484 passed, 255 skipped.
The relationship and benchmark browsers pass desktop/mobile with synthetic data
on disposable PostgreSQL databases. Ruff checks 158 Python files; Django,
migration drift and static collection pass. The existing database helper and
frozen installation started the restored local workflow; migrations were already
applied. A fresh development server was started on the verified available port
8004 and passed the saved actual HTTP readiness checks without market requests.
All development account/portfolio/journal/watchlist counts and temporary browser
database counts are zero. The original specification remains unchanged.
[Sharpe](sharpe.md) is implemented. [Selected-period profitability](profitability.md) is implemented. [Annual return on assets/equity](capital-returns.md) is implemented. [Annual revenue and earnings growth](growth.md) is implemented. Next: valuation multiples with explicit price and earnings dates. Live acceptance and production remain unverified.


## Sharpe module

Version 0.19 adds optional daily and annualized Sharpe to the existing confirmed
daily-return load. Enter an explicit annual simple risk-free percentage from
-100 to 100 and confirm the constant-rate and 252-session convention. Blank
selection skips Sharpe. Require twenty complete returns and positive sample
volatility; preserve undefined/missing states without filling observations.
Calculations reuse the same exact portfolio factors with no additional provider
requests, journal reads/writes, dependency, migration or paid service. See
[Sharpe definitions, examples and limitations](sharpe.md).

```sh
uv run --frozen --env-file .local/database-test.env python manage.py test --noinput
python3 tests/browser_sharpe.py
python3 tests/browser_relationships.py
python3 tests/browser_daily_returns.py
```

Full PostgreSQL: 739 passed without skips. SQLite: 484 passed, 255 skipped.
Sharpe, relationship and daily-return browsers pass desktop/mobile using synthetic
prices in disposable PostgreSQL databases. Ruff checks 158 Python files; Django,
migration drift and static collection pass. Frozen install, recognized local
PostgreSQL startup and already-applied migrations pass; setup is repeatable.
A fresh owned server was started on the verified available port 8004 and passed
actual HTTP readiness without provider requests. All development model counts
and temporary browser-database counts remain zero; the original specification
SHA256 is unchanged. No new live API request was needed. Live acceptance,
verified time-varying risk-free series and production remain unverified.
[Selected-period profitability](profitability.md) is implemented. [Annual return on assets/equity](capital-returns.md) is implemented. [Annual revenue and earnings growth](growth.md) is implemented. Next: valuation multiples with explicit price and earnings dates.

## Version 0.20: selected-period profitability

Income statements now show gross, operating and net profit margins from the
already loaded source observations. Valid supplied period dates, complete data,
explicit USD units and positive revenue are required. Missing inputs remain
explained unavailable values; zero profit and losses are retained. Exact rational
calculation rounds only the final percentage to two places, half up. See
[profitability definitions and examples](profitability.md).

From the repository root, with the existing private PostgreSQL helper ready:

```sh
export UV_CACHE_DIR=/workspace/.cache/uv
uv sync --frozen
python3 scripts/development_database.py
uv run --frozen --env-file .local/database.env python manage.py migrate --noinput
uv run --frozen --env-file .local/database-test.env python manage.py test --noinput
python3 tests/browser_profitability.py
python3 tests/browser_fundamentals.py
```

PostgreSQL: 739 passed, no skips. SQLite: 484 passed, 255 PostgreSQL-only skips.
The module adds 29 tests (21 pure calculation cases and eight statement-page
cases). Both browser runners pass desktop/mobile using synthetic observations;
no live API request or development account is created by those runners. Ruff
lint/format checks 158 Python files; Django checks, migration drift and static
collection pass. No dependency, migration or additional provider request is added.

The frozen installation and private database helper were repeated successfully.
A fresh current-source development server started on the checked free port 8004.
Actual HTTP readiness checked landing status, empty research forms, account
forms/CSRF, signed-out private-route redirects and local assets twice without
requesting provider data. All six development model counts and temporary browser
database counts are zero. The original specification's SHA256 is unchanged.
Credential presence does not prove API access: current managed credential/network
observations remain unknown. New-margin live acceptance, publication/restore and
production remain unverified. Preserve the proxy, CA and existing vault binding.

[Annual return on assets/equity](capital-returns.md) is implemented. [Annual revenue and earnings growth](growth.md) is implemented. Next: valuation multiples with explicit price and earnings dates.


## Version 0.21: annual return on average assets and equity

Choose **View return on assets and equity** from instrument details or company
financials, enter a fiscal year and **Load annual returns**. The explicit annual
load uses up to seven shared-budget requests for one instrument and three
lookup/value pairs. Opening and closing balance sheets must align to the income
period boundaries. Both endpoint balances must be positive with explicit USD
units. See [annual return definitions](capital-returns.md).

From the existing repository root:

```sh
export UV_CACHE_DIR=/workspace/.cache/uv
uv sync --frozen
python3 scripts/development_database.py
uv run --frozen --env-file .local/database.env python manage.py migrate --noinput
uv run --frozen --env-file .local/database-test.env python manage.py test --noinput
python3 tests/browser_capital_returns.py
python3 tests/browser_profitability.py
python3 tests/browser_fundamentals.py
uv run --frozen --env-file .local/database.env python manage.py runserver 127.0.0.1:8005 --noreload
```

The 38 annual-return tests cover exact average balances, two-place half-up
percentages, zero/loss/missing inputs, unit/year/date/identity alignment, partial
responses, seven-stage failure/quota stops, independent metrics, shared request
limits and source escaping. The initial full PostgreSQL run exposed an existing
identical-split race during unlocked preflight; that timing gap is now fixed
without changing locked append checks or immutable history. A deterministic
PostgreSQL regression plus existing journal/action checks pass (79 focused tests).

The final full PostgreSQL suite passes 739 tests without skips. SQLite passes
484 and skips 255 PostgreSQL-only cases. All three listed browsers pass with
synthetic observations on desktop/mobile; normal startup never uses fixtures.
Ruff lint/format checks 158 Python files; Django checks, migration drift (none)
and static collection pass. Dependencies remain locked; no migration is added.

After the journal fix, managed terminal cancellation left port 8004 occupied
and process ownership could not be inspected through the command sandbox. A
fresh current-source server was started on the checked free port 8005; readiness
uses that port consistently. Do not kill an unknown process based on its port.
Actual HTTP checks cover landing/provider status, empty research forms including
annual returns, account forms/CSRF, signed-out private-route redirects and assets
without provider calls. Repeated frozen installation, recognized PostgreSQL
startup and migrations pass. All six development model counts and temporary
browser database counts remain zero; the original specification SHA256 is unchanged.

Current managed phase is running with current observations, but credential and
network-enforcement observations remain unknown. Key presence does not prove API
access. No live API call was made for annual-return acceptance. Saved startup
instructions, publication, fresh-task restoration and production are separate;
saving the draft does not execute or publish it. Preserve proxy/CA and existing
credential bindings; no new paid service or network destination is added.

[Annual revenue and earnings growth](growth.md) is implemented. Next: valuation
multiples with explicit price and earnings dates.


## Version 0.22: annual revenue and earnings growth

From instrument details or company financials choose **View annual revenue and
earnings growth**, select the current FY and **Load annual growth**. Both income
statements must have adjacent supplied annual periods, explicit USD units,
complete data and known version classifications. Dollar changes are exact;
percentage growth requires positive prior values. Loss transitions and duration/
version warnings are explicit. See [growth rules](growth.md).

From the existing repository root:

```sh
export UV_CACHE_DIR=/workspace/.cache/uv
uv sync --frozen
python3 scripts/development_database.py
uv run --frozen --env-file .local/database.env python manage.py migrate --noinput
uv run --frozen --env-file .local/database-test.env python manage.py test --noinput
python3 tests/browser_growth.py
python3 tests/browser_capital_returns.py
python3 tests/browser_profitability.py
python3 tests/browser_fundamentals.py
uv run --frozen --env-file .local/database.env python manage.py runserver 127.0.0.1:8005 --noreload
```

The module adds 44 tests: 26 calculations, five adapter, eleven page and two
form/service cases. Focused growth/annual-return/margin/statement: 145 passed.
Full PostgreSQL: 739 passed without skips. SQLite: 484 passed, 255 PostgreSQL-only
skipped. The four listed browsers pass desktop/mobile using synthetic loopback
servers. Ruff lint/format checks 158 Python files; Django checks, migration drift
(none) and static collection pass. No new dependency or migration is added.

The frozen install and recognized private PostgreSQL helper were repeated;
migrations were already applied. A fresh current-source server started on the
checked free port 8005 and actual saved HTTP readiness passed twice, including
the new empty growth form, existing research/account forms, CSRF, signed-out
private-route redirects and local assets without provider requests. All six
development model counts and temporary browser database counts are zero. The
original specification SHA256 is unchanged. The process PID written by this
turn's launching Python process is only a current-turn diagnostic, never a
reusable PID or evidence that a service survived restoration.

Current phase is running with current observations, but managed network
enforcement and credential readiness remain unknown. Key presence does not
prove live API authorization. The new growth workflow was not accepted against
live Intrinio data. Preserve the inherited proxy, CA trust and existing vault
bindings. No paid service, destination or market-data persistence is introduced.
Saved startup instructions, publication, fresh-task restoration and production
remain separate; saving a draft does not execute or publish it.

Next: valuation multiples with explicit price and earnings dates.

## Version 0.23: selected-year P/E — October 11, 2026

[Annual earnings valuation multiples](multiples.md) adds independent basic and
diluted FY P/E. The initial `/stocks/<security_id>/multiples/` form requests no
data. A valid load uses at most four shared-budget requests: one instrument,
one annual income lookup/value pair and one exact-date single-page price request.
Select an explicit earnings FY and raw closing-price date, and confirm listed
share-class and split compatibility. Confirmation is an assumption; the company
association alone cannot establish it.

Require a full supplied annual period, complete sources, matching USD
instrument/venue and positive EPS with explicit `usdpershare` units. Missing,
zero/loss EPS or unsuitable closes have explained unavailable states. No
adjusted close, previous date, alternate EPS or inferred share count substitutes.
The page shows dates, classification and filing/update/retrieval metadata, and
explains selected-FY/current-version versus TTM, forward or historical-as-known
ratios. Read the guide before changing financial definitions.

Run the focused checks and optional browser acceptance from the checkout:

```sh
export UV_CACHE_DIR=/workspace/.cache/uv
uv run --frozen --env-file .local/database-test.env python manage.py test tests.test_multiples tests.test_growth tests.test_profitability tests.test_capital_returns --noinput
python3 tests/browser_multiples.py
python3 tests/browser_growth.py
python3 tests/browser_capital_returns.py
python3 tests/browser_profitability.py
python3 tests/browser_fundamentals.py
```

Observed verification: focused 152 passed; full PostgreSQL 780 passed with no
skips. Full explicit SQLite discovered 780, passed 525 and skipped 255
PostgreSQL-only cases. Ruff lint/format checks 164 Python files. Django system
checks, migration drift (none), static collection and frozen installation pass.
All five listed browser runners pass on desktop/mobile with explicit test-only
synthetic sources. The P/E runner covers eleven modes, required unchecked and
keyboard confirmation, date/source metadata, response cleanup and mobile layout.
Normal startup never enables fixture transports.

The first full PostgreSQL attempt and first drift check encountered a stopped
database container. The recognized private container was restarted through
`scripts/development_database.py`, without deleting/resetting data. PostgreSQL
performed automatic recovery and reached readiness. Repeated migrations and
drift checks then completed without connection warnings; the full suite passed.
If socket connections fail after a restore, inspect the managed local Docker
daemon and recognized container, then use the same supported helper. A previous
successful helper run does not guarantee a process is still running.

A free port8005 was checked before launching a fresh current-source development
server. Updated HTTP readiness passed twice, including the untouched initial
P/E form, existing research forms, assets, CSRF/no-store account forms and
signed-out private redirects. It creates no records and makes no provider calls.
All six development model counts remain zero; the original specification matches
the supplied text after line-ending normalization. Only this turn's owned server handle/PID is usable for diagnostics;
do not reuse old PIDs or infer ownership from a port.

No new dependency, database migration, paid service, network destination or live
API call was introduced. The existing vault binding is retained. Current-instance
tests do not establish new live P/E acceptance, public-display licensing,
production operations or a new-task restore. Updated `start_skill` instructions
are saved for review; saving does not apply or publish the environment.

Next: bounded multi-year financial statement trends with explicit periods and
source-version provenance.

## Version 0.24: annual statement trends — October 11, 2026

[Annual financial statement trends](trends.md) now supports two to four annual
income, balance-sheet or cash-flow periods. The initial
`/stocks/<security_id>/trends/` form makes no provider request. Select one
statement, a last FY and a period count. Each load reuses one verified instrument
and a lookup/value pair per FY: five, seven or nine requests under the existing
shared quota. Earlier search/details actions still count against that allowance.

Three defined USD metrics per statement have signed interactive bars, exact
observation tables, adjacent changes and per-FY source versions. Observations
require complete, duplicate-free classified sources and explicit USD units.
Annual flows require supplied full-year windows; balance sheets remain endpoint
balances. Incompatible pairs retain valid values but withhold changes. Missing
middle values break both adjacent comparisons, without interpolation or jumping
to the last available year. Zero/negative bases keep exact dollar changes but
have unavailable percentage changes. Read the guide before changing definitions.

From the existing checkout, run relevant focused/browser checks:

```sh
export UV_CACHE_DIR=/workspace/.cache/uv
uv run --frozen --env-file .local/database-test.env python manage.py test tests.test_trends tests.test_growth tests.test_fundamentals --noinput
python3 tests/browser_trends.py
python3 tests/browser_fundamentals.py
python3 tests/browser_smoke.py
```

Observed results: 38 new tests, focused 116 passed; full PostgreSQL 818 passed
without skips. Full explicit SQLite discovered 818, passed 563 and skipped
255 PostgreSQL-only checks. Ruff lint/format checks 170 Python files; Django,
migration drift (none), static collection and frozen installation pass.
The actual trend browser covers nine desktop/mobile cases across all three
statement types plus mixed classifications, week years, gaps, stub periods,
partial middle responses and missing tags. It verifies keyboard/pointer chart
readouts, exact tables, source cards, mobile layout and 429 cleanup. Existing
three-statement and search/selection/daily-chart browser regressions also pass.

The first browser check found that the script was placed in a block the shared
base layout does not render. Correct the inclusion and add a page assertion;
actual keyboard/pointer checks now pass. The existing local point script is
reused without modification. No chart library, CDN or Node build is needed.

Port8005 was checked free before starting a fresh current-source server. Revised
actual HTTP readiness passed twice and again after repeat frozen installation,
recognized database helper and already-applied migrations. The added startup
check opens only the initial empty trend form, without provider calls or records.
All six development model counts and temporary browser database counts remain
zero; the original specification SHA256 is unchanged. Development processes
must restart in future tasks; never reuse old PIDs or infer ownership from a port.

Current runtime observations are running/current, but network enforcement and
vault-key readiness are unknown. Preserve existing proxy/CA trust, TLS and vault
bindings; a present key variable does not establish remote authorization. No
live API call, new destination, dependency, migration, paid service or persisted
market dataset was added. New trend live acceptance, licensing, production and
fresh-task restoration remain unverified. Updated startup instructions are saved
as `start_skill` for review; saving does not apply or publish the environment.

Next: stock-level historical volatility and drawdown with explicit price basis.

## Version 0.25: stock historical volatility and drawdown — October 11, 2026

[Stock risk](stock-risk.md) now accompanies the existing daily-price load. It
reuses the same response, explicit basis and shared per-page quota; no extra
request, persistence, dependency, migration or hosted service is needed. The
initial form suggests 90 calendar days ending on the preceding UTC day. Risk
requires a complete supported U.S. equity session grid, confirmed strictly
positive selected closes, dates from 2000 ending before today UTC, and at most
366 days. Weekend/holiday endpoints use the sessions inside the range. Gaps,
partial paging, zero/missing prices and unknown/incomplete periods withhold the
entire risk sample while keeping supplied price observations available.

Exact fractional simple returns supply sample volatility (at least two returns),
252-session annualization (at least twenty), signed daily drawdowns and positive
maximum loss. The opening close supplies the initial peak; first deepest episode,
latest equal peak and first recovery rules are documented. A fresh 80-digit
Decimal square-root context and final half-up four-place percentages isolate
ambient numeric settings. Raw/adjusted corporate-action effects and methodology
limits are explicit, without currency inference or portfolio-flow accounting.

Optional focused and browser checks from the repository root:

```sh
uv run --frozen python manage.py test tests.test_stock_risk tests.test_stock_risk_pages tests.test_prices tests.test_risk --noinput
python3 -m tests.browser_stock_risk
python3 -m tests.browser_smoke
```

Observed: 39 new tests, focused 88 passed; full PostgreSQL 857 passed without
skips. SQLite discovered 857, passed 602 and skipped 255 PostgreSQL-only cases.
Ruff lint/format checks 176 Python files; Django checks, no migration drift,
static collection and frozen setup pass. The pure calculator imports without
Django initialization. Eight synthetic browser scenarios pass desktop/mobile:
complete, split, short, gap, unknown status, zero, partial pages and unsupported
exchange, including keyboard/pointer readouts, independent figures, tables,
overflow and 429 cleanup. Existing search/details/price browsers pass.

Normal application live AAPL XNAS/USD verification passed raw and adjusted
prices for August 12–October 10, 2026, with 42 completed closes through October 9
and 41 returns. Both supplied bases produced daily volatility 1.2748%, annualized
20.2375% and maximum drawdown 3.9213%. Actual desktop/mobile keyboard/table and
overflow checks pass. Four backend requests use the existing vault binding and
subscription; no keys, raw responses, live screenshots or development users
are retained. Wider coverage, vendor methodology, quotas, display/cache rights
and production are separate checks.

Port 8005 was verified free before starting a new current-source normal server.
Saved research/account/asset/private-redirect readiness passed without provider
calls or account creation. All six development model counts and temporary
browser database counts remain zero; the original specification is unchanged.
Process handles from previous tasks are not reused. Reusable startup instructions
are saved separately for review; saving does not apply or publish the environment.

Next: bounded trading-volume charts with explicit raw/adjusted basis and missing-data rules.

## Version 0.26: raw and adjusted daily trading volume — October 11, 2026

[Trading volume](volume.md) now uses the existing historical-price response,
without another endpoint or request. The form has an independent volume basis,
defaulting to raw for older saved queries. Exact Decimal raw/provider-adjusted
share counts retain fractions and known zeros. Optional absent/null fields
remain unavailable; malformed supplied fields fail the complete response.
Numeric bounds are nonnegative finite numbers up to 1e18, 36 digits and exponent
-18 through 18. No currency turnover, sums, averages or fallback is inferred.

Confirmed daily observations have rational-geometry bars, zero baseline,
keyboard/pointer inspection and an exact newest-first table with both fields
and period status. Missing/unknown/incomplete values have no bar; known zero
has a selectable baseline point. Partial history remains labeled and volume
can be available without price fields. One local inspector script loads after
all price/risk/volume figures. Calendar coverage/freshness and the vendor's
adjustment methodology are not inferred.

Optional checks from the repository root:

```sh
uv run --frozen python manage.py test tests.test_volume tests.test_prices tests.test_stock_risk_pages tests.test_valuation tests.test_benchmarks --noinput
python3 -m tests.browser_volume
python3 -m tests.browser_smoke
python3 -m tests.browser_stock_risk
```

Observed: 27 new tests, focused regression 93 passed. Full PostgreSQL 884 passed
without skips; SQLite discovered 884, passed 629 and skipped 255 PostgreSQL-only
cases. Ruff lint/format checks 180 Python files, Django checks, no migration drift,
static collection and frozen setup pass. The volume module imports without
Django initialization. Eight volume scenarios pass desktop/mobile with synthetic
test-only data, as do existing search/details/prices and all eight stock-risk
scenarios. Keyboard/pointer controls, exact readouts, tables, independent figures,
script inclusion, overflow and error cleanup pass. No development records or
test databases are created by these public fixture servers.

Normal-application live AAPL XNAS/USD acceptance passed raw and adjusted volume
over August 12–October 10, 2026, each with 42 completed observations through
October 9 and desktop/mobile keyboard/pointer/table/overflow checks. Price/risk
remain available. Four requests used the existing key and subscription for
search, reference and two history loads. No key, raw response or live screenshot
was stored and no account created. Wider coverage, adjustment methodology,
quotas, rights and production remain separate verification.

Current-source normal startup and saved form/asset/private-redirect readiness
pass without provider calls or account creation. Only this task's server was
stopped/restarted to include the final presentation text. Repeated frozen setup
and recognized PostgreSQL startup preserve state. All six development model
counts and temporary browser database counts remain zero; the original
specification is unchanged. No dependency, migration, service, destination or
paid subscription was added. Startup draft saving does not apply or publish it.

Next: market capitalization research with explicit price/share dates and currency.


## Version 0.27: dated company market capitalization — October 11, 2026

See [market capitalization definitions](market-capitalization.md). The provider's
company-level exact-date `marketcap` value is used rather than multiplying a
listing price by weighted-average earnings shares. The live balance-sheet feed
had no outstanding-share count. Separate tag metadata confirms USD independently
of listing currency. Underlying price/share-count dates, counts and methodology
are not supplied and remain explicitly unavailable/unverified.

The load reserves shared quota for each of three fixed backend requests, requires
matching company identity and one exact-date observation, never follows a cursor
and uses safe provider errors. Missing, null and incomplete values remain
unavailable; an observed zero stays zero. No data is requested by a blank form.
No dependency, migration, secret, service or subscription was added.

```sh
uv run --frozen --env-file .local/database-test.env python manage.py test tests.test_capitalization tests.test_multiples tests.test_fundamentals --noinput
python3 tests/browser_capitalization.py
```

Observed: 30 new tests; focused regression 105 passed. Full PostgreSQL 914 passed,
no skips. SQLite discovered 914, passed 659 and skipped 255 PostgreSQL-only cases.
Ruff lint/format checks 185 Python files. Django checks, migration-drift checks,
static collection and fresh normal startup/readiness pass. All seven synthetic
browser scenarios pass desktop/mobile with error/quota checks and owned-process
cleanup; no account or temporary browser database is created.

Live normal-app AAPL/XNAS acceptance passes for October 9, 2026: positive USD
company observation, source/date and unknown-input labels, desktop/mobile date
controls, local-only browser requests and no-store. No live screenshot, raw
response or value was retained. Six development record counts and temporary
browser database count remain zero. Original specification checksum is unchanged.

Start the normal application with the frozen development database settings and
an owned TTY; verify a free port before starting. Managed non-TTY cancellation
can leave workers alive. Never reuse a stale process handle or kill by port;
terminate only processes whose current-task ownership has been established.
The saved startup instructions now include the blank market-cap form check.
Production remains pending. Next: watchlist market information and saved preferences.


## Version 0.28: watchlist market information and saved preferences — October 11, 2026

[Feature definitions and verification](watchlist-market.md). Private watchlists
now save default price/volume bases and date-added/ticker instrument order. Saves
make no provider calls and require CSRF-protected POST. The additive migration
`watchlists/0002_market_preferences` preserves existing lists/bookmarks with raw,
raw and date-added defaults and enforces database choices.

The optional daily-information form loads one to five selected owned instruments
for an exact date, reserving shared quota for each single-page daily request. No
reference refresh, cursor following, polling, caching, retries or cross-currency
sum is introduced. Independent selected close/volume, response currency/MIC,
requested date and UTC retrieval/source details stay explicit. Missing, partial
and unconfirmed values remain unavailable; zero/fractional values are preserved.
Request-limit errors stop remaining loads while keeping valid earlier rows and
return 429/Retry-After. Authorization/item membership are checked again after I/O.

```sh
uv run --frozen --env-file .local/database.env python manage.py migrate --noinput
uv run --frozen --env-file .local/database-test.env python manage.py test tests.test_watchlist_market tests.test_watchlists --noinput
python3 tests/browser_watchlist_market.py
python3 tests/browser_watchlists.py
```

Observed: 41 new tests; focused regression 77 passed. Full PostgreSQL 955 passed
without skips. SQLite discovered 955, passed 675 and skipped 280 PostgreSQL-only
cases. Ruff lint/format checks 191 Python files. Django checks, no migration drift,
static collection, repeated frozen setup and fresh normal readiness pass. Eight
new synthetic browser scenarios and the existing watchlist workflow pass desktop/
mobile with owned temporary PostgreSQL database cleanup. Mobile source/table UI
was visually inspected; fields have connected accessible help and table scrolling.

Live AAPL/XNAS acceptance for October 9 passes through a disposable application/
PostgreSQL database with the actual provider transport and existing vault key:
saved defaults, both raw/adjusted closes and volumes, date/source/currency/
completion labels, local-only browser requests and desktop/mobile controls.
Five total backend calls covered search/details/bookmark/two daily loads. No live
values, responses or screenshots retained. Temporary accounts/lists/database
were removed; six development counts and temporary browser DB count are zero.
The original specification checksum is unchanged. No new dependency, secret,
paid service or subscription was added.

An owned normal development server was stopped and restarted after final UI
changes. Terminal cancellation left its worker alive even with a TTY. Exact
current-task argv, UID, start time and parent relationship were verified before
terminating only that worker; the free port and fresh normal readiness were then
rechecked. Do not kill by port, reuse stale handles or assume terminal exit means
worker exit. Saved startup checks now cover unauthenticated market/preferences
redirects. Production remains pending. Next: broader live-data and complete
user-journey acceptance testing, followed by release safeguards and private deployment.


## Version 0.29: connected account and live research acceptance — October 11, 2026

[Release evidence, reproduction and remaining work](release-acceptance.md).
One continuous account journey passes through idempotent trade recording,
dividends/splits, signed correction/audit, FIFO, end-of-day funding, matched TWR
and daily returns, valuation/allocation, saved watchlist defaults and owner
isolation, then password change and renewed sign-in. Its real PostgreSQL
records and synthetic transport are confined to the owned disposable database.

Live acceptance exposed incorrectly named gross/operating profit inputs.
Margins now use `totalgrossprofit`/`totaloperatingincome`; income trends use
`totaloperatingincome`. The live follow-up independently recomputes all three
AAPL margins, ROA/ROE, revenue/net-income growth, basic/diluted annual P/E and
three two-year income trends. Source/version and assumption labels, charts,
tables and desktop/mobile layouts pass. Microsoft acceptance covers its
USD/XNAS listing only. P/E share-basis compatibility remains an explicit user
assumption, and current statement versions are not historical-as-known data.

```sh
python3 tests/browser_release_journey.py
python3 tests/browser_profitability.py
python3 tests/browser_trends.py
# Optional authenticated acceptance; never part of ordinary startup/CI:
python3 tests/browser_live_research.py --financial-follow-up
```

The first attempt used six calls before the margin assertion failed. The
successful follow-up's actual backend count is 26, within an enforced ceiling;
total 32. It skips already verified price/detail and market-cap work rather than
re-fetching them. The reusable default full-live mode has a ceiling of 32 but
was not completed this task. Existing quotas, proxy, vault key and TLS remain
intact; pacing waits for real minute windows. No live payload/value/screenshot
is retained, and no dependency, migration or paid service was added.

Two new field-name regressions bring the full PostgreSQL suite to 957 passed
without skips. SQLite: 677 passed and 280 PostgreSQL-only skipped. Focused
margin/trend regression: 69 passed. Ruff lint/format checks 194 files. Three
synthetic margin and nine synthetic trend scenarios, the continuous account
journey, repeated frozen setup, no migration drift, Django/static checks and
fresh normal readiness pass. All six development model counts and owned
browser-database counts are zero; the specification checksum is unchanged.

The normal development server was launched on a verified-free port 8005 and
its readiness checked without provider calls or account creation. Browser
children terminated cleanly and removed their own databases. New tasks must
restart normal processes and verify ownership independently; do not reuse this
task's terminal handles or infer process ownership from a port.

Two private-MVP release work packages remain: release safeguards (production
settings, CI review, shared quotas, backup/restore), then private deployment
with a low-cost target and applicable data rights checked. No remote CI run,
public deployment or production-readiness claim is made here.


## Version 0.30: release safeguards — October 11, 2026

[Release definitions](release-safeguards.md) and [backup/recovery](backups.md).
Production now requires shared PostgreSQL request admission for both market
requests (10/client, 30 total/minute) and account writes (10/client, 60 total).
The additive operations migration creates two possible bounded scope rows;
worker restarts do not refund allowances. Database-clock windows, durable row
locks and short lock/statement timeouts protect admission before external/auth
work. Store errors, missing migrations, invalid state and outer transactions
fail closed with fixed no-store 503s. No Redis or provider data cache is added.
Development retains memory mode; it can opt into PostgreSQL for integration.

Production configuration defaults to untrusted forwarded HTTPS headers. An
explicit production-only proxy flag requires independently verified header
replacement and private application ingress. Client address headers remain
untrusted. Two actual Django HSTS advisories (subdomain coverage and preload)
remain printed and documented; the synthetic production check fails every
unexpected warning/error rather than enabling unverified domain-wide policies.
It makes no remote database or provider connection. CI now includes that guard
and a separate SQLite pass with PostgreSQL fields cleared; remote CI is unrun.

```sh
export UV_CACHE_DIR=/workspace/.cache/uv
uv run --frozen --env-file .local/database.env python manage.py migrate --noinput
uv run --frozen python scripts/check_release_configuration.py
uv run --frozen --env-file .local/database-test.env python manage.py test tests.test_release_safeguards tests.test_backups --noinput
python3 tests/browser_release_journey.py --shared-limits
uv run --frozen python scripts/verify_backup_restore.py --local-container
```

The actual export command creates a new private custom-format archive without
clobbering files/symlinks and checks its table of contents. The disposable
recovery drill recreates every model/M2M and migration-history row digest,
then confirms corrected FIFO accounting, password verification, group/user
permissions, decoded sessions with the same separately provisioned fixture
secret, owner isolation and database journal immutability. Source/target OIDs
and ownership are verified before cleanup; both databases and synthetic archives
are removed. No development user data was exported or live provider requested.
Matching native client tools, host TLS and off-machine retention remain specific
to the chosen deployment; no backup service or destination was purchased.

Observed: 25 new tests and 25 focused checks pass. Full PostgreSQL 982 pass
without skips; SQLite 690 pass and 292 PostgreSQL-only skip. Ruff lint/format
checks 207 files. Both memory/shared connected browser journeys, repeated
frozen setup, additive migration with no drift, Django/static and fresh normal
readiness checks pass. Six development business-model counts, operational
counter rows and owned browser/backup database counts are zero. The original
specification checksum is unchanged. No new dependency or paid service.

An existing port 8005 was occupied and left untouched. Port 8006 was verified
free before launching this task's normal development server and executing the
saved readiness checks there, without provider calls or account creation. The
current startup instructions use 8006; historical sections retain earlier ports.
Future tasks must independently restart/verify processes and must not reuse this
task's handles/PIDs or kill by port.

One planned private-MVP work package remains: prepare a low-cost private host,
process/static serving, HTTPS, database roles/TLS, persistent storage and
scheduled encrypted off-machine backups; check applicable Intrinio rights;
then perform controlled deployment and private smoke checks. Release evidence
does not establish real-host readiness or completion of optional advanced scope.


## Version 0.31: portable production serving and private access — October 11, 2026

[Serving configuration, commands and limits](production-serving.md).
Gunicorn 26.2.0 and WhiteNoise 6.12.0 are now pinned with artifact hashes. The
production entry point requires validated production settings and a real
collected static manifest before replacing its process with Gunicorn. It starts
with one worker, supports bounded explicit port/bind/worker settings, disables
access logs and implicit server scheme-header trust, and retains shared quotas.
No automatic startup migration/account creation or Node/static hosting service.

Production defaults to a private research site and registration closed. Active
sessions can reach research; anonymous/inactive users cannot. Account-creation
links are hidden when disabled. Development keeps its public/local defaults.
Use deploy/production.env.example for hosted settings, not the development file.
Operator user provisioning, real database TLS, ingress and data rights remain
selected-host operations. The process-only /health/live/ endpoint does not query
PostgreSQL or Intrinio and is the only plain-HTTP redirect exemption.

```sh
export UV_CACHE_DIR=/workspace/.cache/uv
uv run --frozen --env-file .local/database-test.env python manage.py test tests.test_production_serving tests.test_environment tests.test_release_safeguards --noinput
uv run --frozen python tests/production_smoke.py
```

Thirteen new tests and 43 focused checks pass. PostgreSQL 995 pass without skips;
SQLite 703 pass and 292 PostgreSQL-only skip. Ruff lint/format 215 files pass.
Actual two-worker Gunicorn smoke verifies default untrusted scheme handling,
controlled proxy opt-in, private routes, closed registration, secure cookies,
fingerprinted gzip assets/cache/security headers and safe account failure when
synthetic storage is unavailable. It stops only its own process groups and makes
no provider or hosted database request. CI now includes that same smoke command;
remote CI was not run. Existing shared-limit portfolio journey also passes.

Repeated frozen setup checks 24 installed packages. Migrations have no drift and
Django/static checks pass. A free port 8006 was verified before a fresh normal
server; saved readiness now also covers the no-store process-only health path.
All business/counter development records and browser/backup test databases remain
empty; the original specification checksum is unchanged. Processes must restart
in future tasks; never reuse historical handles or kill by port.

The requested Render terms verification is still blocked: docs.render.com returns
proxy 403 and the current runtime allowlist has only the existing Intrinio custom
host. A network draft adds docs.render.com and preserves Intrinio plus the package
preset. It must be reviewed/saved in Environment settings before the affected
request is retried. The serving package is independently tested; that does not
establish Render's limits, account eligibility or a hosted deployment. No host
resource, paid service, source push or actual user account was created. Next:
apply documentation access, verify terms, then prepare the chosen host's concrete
configuration and private deployment.

## Render deployment preparation — October 12, 2026

[Reviewable candidate and remaining release steps](render-deployment.md),
[native build](../deploy/render-build.sh) and
[Free-service template](../deploy/render.yaml.template). The application remains
v0.31. No source push, hosting resource, real user or charge was created.

Fresh and repeated synthetic production builds pass, installing pinned uv inside
ignored `.render-tools` and 23 frozen runtime packages into a separate ignored
validation environment. The unused loopback database and blank provider key prove
the build needs neither remote service. Actual Gunicorn/WhiteNoise smoke passes
using the fresh runtime packages, and owned processes stop. The build does not
migrate or create accounts. Existing HSTS subdomain/preload advisories remain
visible. No additional Python test was added or full-suite run repeated; the prior
995 PostgreSQL result remains release evidence rather than a new result.

Ruff check/format 215 files, shell syntax, frozen development setup 24 packages,
local PostgreSQL/migrations/no drift, static collection and a fresh normal server
on verified-free port 8006 all pass. The saved readiness script, including liveness,
passes without provider calls or new records. All seven business/counter counts
are zero; the original specification checksum is unchanged. Startup must still
restart processes in a fresh task; do not reuse historical process handles.

The earlier documentation-domain addition is now in the running desired policy.
`https://docs.render.com/free` returns 301 to `https://render.com/docs/free`, whose
proxy connection is denied. The saved draft additionally allows `render.com`,
preserving both existing custom hosts and the package-manager preset. Review/save
and publish that draft before retrying the redirected destination. Current Free
limits and the complete template schema remain unverified. Account access, source
publication, database/TLS, initial user, encrypted off-machine backup scheduling
and hosted acceptance remain the actual deployment work.

## Hosting terms verified after network publication — October 12, 2026

The current desired custom allowlist includes `api-v2.intrinio.com`,
`docs.render.com` and `render.com`. Render's Free, pricing, Blueprint/schema,
Python, ingress, health and billing-related pages now return HTTP 200 through the
inherited proxy with TLS verification. No additional network change is needed
for those reads. Runtime policy state remains `unknown`, so this verifies specific
requests rather than all policy enforcement. Earlier denial notes are historical.

The [updated comparison](free-hosting-comparison.md) records actual allowances,
cold starts, external-traffic suspension and payment-backed overages. Render's
expiring/unbacked Free database is excluded. The [deployment draft](render-deployment.md)
uses a separate Neon database and trusted operator machine for migration, the
first user and backups because Free has no shell or one-off jobs. Neon official
sources verify direct-endpoint guidance for migration/dump and CA verification.
No actual hosted connection, billing setting, data right or backup destination
has been tested.

The updated review template passes Render's live official JSON schema, with one
explicit Free service, private access, `autoDeployTrigger: "off"` and preview
generation off. Shell syntax and Ruff check/format (215 files) pass. Frozen setup
(24 packages), local PostgreSQL/migrations/check/static and a fresh normal server
on verified-free port 8006 pass the existing saved readiness script. All seven
business/counter counts stay zero; the original specification checksum is
unchanged. Application/dependencies remain v0.31 and the prior 995-test result
was not rerun for these documentation/template changes.

The existing installation and service startup commands remain valid; no new
install command, service or secret requirement is introduced by verification.
Hosting credential variables are absent, no outbound hosting identity/app is
available, and the user was asked whether Render/Neon accounts exist. Establish
the Free account/workspace access before authorizing a concrete external release.
No source was pushed, hosting resource created, real user provisioned or charge
introduced. Source publication, real database/ingress TLS, encrypted backups and
hosted acceptance remain the final deployment steps.
