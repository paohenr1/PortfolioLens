# Stock Research & Portfolio Analytics Platform

A stock research and portfolio analytics application powered by Intrinio market data.

Planned features include stock search, financial analysis, portfolio tracking, watchlists, and quantitative research tools.

## Project status

The foundation and core stock-research pages are implemented: stock search,
selectable instrument reference pages, a backend-only Intrinio adapter, request
budgets, safe errors, and 995 automated tests. Search and selection have also
passed desktop/mobile browser checks using labeled fixtures.

Live Intrinio search and instrument lookup passed on October 10, 2026 using the
vault-bound cloud key, including browser search and selection. This verifies
reference access. Historical-price retrieval and raw/adjusted daily charts are
also implemented and passed a live one-year AAPL browser check (251 completed
observations). Company income, balance-sheet, and cash-flow statements are also
implemented, with selected metrics, source units, and explicit fiscal periods.
All three AAPL fiscal-2025 annual pages passed authenticated browser checks.
Normal startup never substitutes fixtures. Account registration, sign-in/out,
password changes, and a private current-user account page are also implemented.
Private USD portfolio creation, listing, and details are now implemented on
PostgreSQL, with owner isolation and concurrency checks. The append-only USD
transaction journal now records deposits, withdrawals, buys, sells, and fees.
FIFO positions, remaining cost basis, and realized sale gains are also
implemented. Explicit-date market valuation and unrealized gains are now
implemented. Cash-inclusive allocation weights and explicit-period time-weighted
returns with confirmed end-of-day cash flows are implemented.
Private watchlists support instrument bookmarks, confirmed removal, saved price/volume
bases and instrument order, and on-demand exact-date closes/volume for up to five
selected instruments. Opening a list makes no market-data request. See
[watchlist market information](docs/watchlist-market.md).
Daily session returns now use the corrected journal and a U.S. equity calendar.

Version 0.29 adds a continuous account/portfolio acceptance journey and bounded
live research checks. Live testing found and corrected Intrinio profit-field
names used by margins and annual operating-income trends. AAPL margins, ROA/ROE,
growth, selected-FY P/E and trends now pass independent arithmetic checks. See
[release acceptance evidence](docs/release-acceptance.md).

Version 0.30 adds shared PostgreSQL limits for production market/account requests,
production configuration checks, stronger CI coverage and a verified private
backup/restore drill. No new dependency or paid service was added. See
[release safeguards](docs/release-safeguards.md) and [backups](docs/backups.md).
One planned work package remains: private deployment with hosting, HTTPS,
persistent storage, backups and applicable data rights verified.

[Free hosting comparison](docs/free-hosting-comparison.md): Render Free web plus
Neon PostgreSQL is the personal prototype shortlist. Render's public limits and
billing behavior are verified; accounts and hosted behavior still need checking.
Hosting is not deployed; Railway's credit and Fly.io's
trial do not establish continuously free hosting for this app.

[Render + Neon deployment draft](docs/render-deployment.md) now includes a
commented Free-service template validated against Render's current official
schema and a locally verified native Python build. Deployment and preview
automation are disabled. The draft creates no hosted service or source publication.

Version 0.31 adds [production serving and private access](docs/production-serving.md):
Gunicorn, compressed static assets, sign-in required by default in production,
closed registration and a process-only health check. Actual runtime smoke tests
pass. Hosting remains unprovisioned; account access, real database/ingress TLS,
backups and hosted acceptance remain release steps.

From an instrument's details, choose **View price history**, set dates and the
price basis, then **Load prices**. The chart supports point inspection and an
accessible values table. It loads only after submission, with a 366-day range
limit and shared request quotas. No new dependency or paid service was added.
The same load now shows stock daily/annualized volatility and drawdown when all
expected completed U.S. equity sessions are present. Basis, sample thresholds,
missing-data rules and source dates are explicit. AAPL acceptance passed for
both bases. See [stock risk definitions](docs/stock-risk.md).
Choose an independent **Volume basis** for raw or provider-adjusted share counts.
The same load supplies interactive daily bars and an exact table, preserving
fractional and zero values while labeling missing/unconfirmed data. Live AAPL
checks passed for both volume bases. See [volume definitions](docs/volume.md).

Choose **View company market capitalization**, select an exact date and **Load
market capitalization**. This uses your existing Intrinio feed for a dated USD
company value, with explicit source details. Missing observations remain
unavailable. Underlying price/share-count dates are not supplied by this endpoint
and are labeled unavailable. See [market capitalization](docs/market-capitalization.md).

Choose **View company financials**, select a statement and fiscal year/period,
then **Load statement**. Values retain their provider units, including USD per
share, and reported/calculated/restated status. Each submission uses at most
three requests from the same budget. Income statements now show selected-period
gross, operating and net profit margins when source units, dates and revenue
support them. See [profitability definitions](docs/profitability.md). No forecasting
or valuation ratios are inferred.

Choose **View return on assets and equity**, enter an annual fiscal year, then
**Load annual returns**. The load uses up to seven shared-budget requests for
annual income and opening/closing balance sheets. Exact date alignment, explicit
USD units and positive endpoint balances are required. The page shows net income,
average balances and all three statement versions. See [annual return definitions](docs/capital-returns.md).

Choose **View annual revenue and earnings growth**, select the current fiscal
year and **Load annual growth**. Two adjacent annual income statements use up to
five shared-budget requests. Dollar changes stay exact; percentages require
positive prior values. Loss transitions, duration and version warnings remain
visible. See [growth definitions](docs/growth.md).

Choose **View annual earnings valuation multiples**, enter an earnings FY and
exact raw-price date, confirm share-class and split-basis compatibility, then
**Load annual P/E**. Basic and diluted EPS are independent, and each requires
positive USD-per-share earnings. Missing/uncertain closes leave both ratios
unavailable. The four-request load shows both dates and source versions; these
are selected-FY ratios using currently retrieved values. See [P/E definitions](docs/multiples.md).

Choose **View annual financial statement trends**, select income, balance sheet
or cash flow, a last FY and two to four annual periods, then **Load annual trends**.
Three defined USD metrics show signed interactive bars, exact tables, adjacent
changes and source versions. Missing years are not bridged; unsuitable periods
leave comparisons unavailable. The default three-year load uses seven requests.
See [trend definitions and limits](docs/trends.md).

Choose **Create account** or **Sign in** to open **My account**. Passwords must
have at least 12 characters; password recovery is not available yet. Accounts
use Django sessions and CSRF-protected forms, without an external auth service.
See [account security and limitations](docs/authentication.md).

Choose **My portfolios** after signing in to create and view your own USD
portfolios. Names are unique within your account, with a fifty-portfolio limit.
See [portfolio setup and ownership rules](docs/portfolios.md).

Open **View transactions** on a portfolio to record a transaction. Cash is
derived from the journal; trade prices are entered manually and never place an
order. Explicit date/order and duplicate-submit protection keep history
consistent. Original entries remain permanent; explicit corrections are now available.
See [ledger rules and limitations](docs/ledger.md).

Choose **Correct** or **Void** on a transaction, enter a reason, and **Preview
correction**. Review its cash, shares, basis and gain effects before **Save
correction**. The audit retains the original; derived accounting and past
valuations/returns use the corrected interpretation. Invalid downstream balances
or a changed journal block saving. See [correction policy](docs/corrections.md).

Choose **Dividend** to record net cash received or **Split** to record explicit
new-for-old terms. Splits change existing shares while preserving lot cost.
Actions are entered manually; cash-in-lieu and automatic action retrieval are
unsupported. See [corporate-action rules](docs/corporate-actions.md).

Choose **View positions and gains** for open FIFO lots, remaining cost basis,
and realized sale gains/losses. Buy fees enter cost; sell fees reduce proceeds.
The page makes no provider requests. See [FIFO accounting policy](docs/fifo.md).

Choose **View market valuation**, select a completed date, check that your
recorded shares match the raw price basis, then **Load valuation**. Holdings,
cash, and raw closing prices use the same date. At most five instruments load
one price request each. Missing prices leave totals unavailable; values are
never filled from adjusted or earlier prices. See [valuation policy](docs/valuation.md).
The same load shows cash and holding allocation weights, rounded to total
100.00%. All weights stay unavailable for incomplete or zero-value portfolios.
Calculating weights makes no extra requests. See [allocation policy](docs/allocations.md).

Choose **View time-weighted returns**, select opening/closing dates, confirm
cash-flow timing and share basis, then **Load returns**. Deposits and withdrawals
are removed from investment performance, using confirmed end-of-day flows after
other activity. Missing boundary prices or zero opening values leave returns
unavailable; intraday funding is rejected. At most eight price requests load.
See [performance definitions and examples](docs/performance.md).

Choose **View daily returns**, select completed session dates and confirm
flow timing/share basis, then **Load daily returns**. Each row compares consecutive
U.S. equity closes, skipping weekends and holidays. A missing required close
leaves adjacent returns and the cumulative result unavailable. The first version
supports 90 calendar days and two instruments, with at most eight requests.
See [daily series rules and examples](docs/daily-returns.md). The same load now
shows daily sample volatility, annualized volatility for at least twenty returns,
and drawdown with peak/trough/recovery dates and an interactive chart. Risk
calculations make no additional price requests. See [risk definitions](docs/risk.md).

Optionally enter a **benchmark security ID** from an instrument's details before
loading daily returns. This compares the portfolio with provider-adjusted prices
on exactly matching sessions, showing an interactive chart and a percentage-point
gap. It adds at most two requests, reusing prices for a benchmark already held.
Missing data leaves the comparison unavailable. Adjustment/index methodology
remains unverified; see [benchmark definitions](docs/benchmarks.md).
The same complete comparison now shows correlation and beta after twenty matched
session returns. Constant-series and short-sample cases are explained explicitly;
statistics use unrounded factors and request no additional prices.
See [relationship definitions and examples](docs/relationships.md).
For **Sharpe**, optionally enter an annual simple risk-free percentage and confirm
the constant-rate/252-session convention. The daily and annualized ratios require
twenty complete returns and nonzero sample volatility. Leaving the rate blank
skips Sharpe; zero must be entered explicitly. No additional prices are requested.
See [Sharpe definitions and assumptions](docs/sharpe.md).

Choose **My watchlists** to create a private list, then **Add to watchlist** on
an instrument's details page. Adding a new instrument uses one reference request;
viewing lists, retrying an existing entry, and removing entries use none. Saved
references are labeled with retrieval times; prices load on demand on research
pages. See [watchlist ownership and request limits](docs/watchlists.md).

The application uses Django 5.2 LTS and Python 3.12. PostgreSQL is required for
private portfolios and watchlists; SQLite remains an option for research/accounts only. The
local PostgreSQL helper runs a free, private Docker database without a hosted
service or published database port. Psycopg connects to PostgreSQL; a free
exchange calendar supplies the daily-return session grid.

Cost is a design constraint: prioritize free software, the existing Intrinio
subscription, and one application instead of multiple paid services.

## Planning documents

- [Installation, configuration, and testing](docs/setup.md)
- [Annual P/E: earnings/price dates, share-basis assumptions and limits](docs/multiples.md)
- [Annual statement trends: periods, bars, changes and source versions](docs/trends.md)
- [Intrinio contracts, limits, and live verification](docs/intrinio.md)
- [Historical prices: definitions, bounds, and chart behavior](docs/price-history.md)
- [Stock volatility and drawdown: basis, sessions and formulas](docs/stock-risk.md)
- [Trading volume: share units, independent basis and coverage](docs/volume.md)
- [Company statements: metrics, units, reporting periods, and limits](docs/fundamentals.md)
- [Accounts: workflow, authorization, and security limits](docs/authentication.md)
- [Private portfolios and PostgreSQL](docs/portfolios.md)
- [Transaction journal: accounting, ordering, and write safety](docs/ledger.md)
- [Transaction corrections and permanent audit trail](docs/corrections.md)
- [FIFO positions: lot allocation, cost basis, and realized gains](docs/fifo.md)
- [Recorded dividends and splits](docs/corporate-actions.md)
- [Market valuation and unrealized gains](docs/valuation.md)
- [Cash-inclusive allocation weights](docs/allocations.md)
- [Time-weighted performance](docs/performance.md)
- [Daily session return series](docs/daily-returns.md)
- [Observed volatility and drawdown](docs/risk.md)
- [Private instrument watchlists](docs/watchlists.md)
- [Implementation history](CHANGELOG.md)
- [Original product specification](docs/product-specification.md)
- [Repository audit, architecture decisions, and development roadmap](docs/development-plan.md)

## Quick start

Run these commands from the repository root, with Python 3.12, uv, and a local Docker daemon:

```sh
export UV_CACHE_DIR=/workspace/.cache/uv
uv sync --frozen
python3 scripts/development_database.py
uv run --frozen --env-file .local/database.env python manage.py migrate --noinput
uv run --frozen --env-file .local/database.env python manage.py runserver 127.0.0.1:8004 --noreload
```

No Intrinio key is needed to start the application and view unavailable states.
Authenticated search requires the key. See the setup document for
optional local environment configuration and production restrictions.

```sh
uv run --frozen --env-file .local/database-test.env python manage.py test --verbosity 2
uv run --frozen ruff check .
uv run --frozen ruff format --check .
```

Implementation will proceed in small, independently testable parts. Financial
calculations will be separated from the web interface and market-data provider,
with comments explaining financial assumptions and important design decisions.
