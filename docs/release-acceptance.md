# Private MVP acceptance

Version 0.29, October 11, 2026. This milestone checks the implemented private
MVP as a connected product and fixes a live financial-field mismatch. It does
not establish production readiness or coverage of every original specification
item. [The original specification](product-specification.md) is unchanged.

## Continuous account journey

`tests/browser_release_journey.py` uses real Django authentication, PostgreSQL,
forms, CSRF and browser JavaScript with an explicitly synthetic provider
transport. Two users and all records exist only in its generated temporary
database. The real development database is not used for acceptance records.

The owner registers, creates a USD portfolio, deposits cash, buys shares, retries
the same signed transaction, records a net dividend and a 2:1 split, sells part
of the position, corrects a fee through its signed preview and audit history,
withdraws cash and adds an explicitly dated end-of-day deposit. The same account
then loads positions, TWR, daily returns, valuation/allocation and a watchlist
with saved preferences. A second user receives private 404/no-store responses
on nine owner routes. A missing-CSRF correction fails with 403. Password change,
sign-out and sign-in with the new password preserve access to the portfolio.

The independent synthetic accounting example is:

| Check | Expected result |
| --- | --- |
| Buy 10 at 10 USD, with 1 USD fee | 101 USD lot cost |
| Split 2:1; sell 4 at 8 USD, with 1 USD fee | 16 shares remaining |
| FIFO basis used by sale | 20.20 USD |
| Remaining basis; realized sale gain | 80.80 USD; 10.80 USD |
| Cash after dividend 5, corrected fee 3 and withdrawal 100 | 832 USD |
| Later end-of-day deposit 50 | 882 USD cash |
| Synthetic January 8 raw close 15.5 | 248 USD holdings; 1,130 USD total |
| Unrealized gain; allocation cash/stock | 167.20 USD; 78.05% / 21.95% |
| January 2–8 TWR and linked daily return | Both 7.8165%; four daily returns |

Opening value is 832 + 16 × 10.5 = 1,000 USD. The January 6 value immediately
before the 50 USD end-of-day deposit is 832 + 16 × 13 = 1,040 USD; after it,
1,090 USD. Linked return is (1,040 / 1,000) × (1,130 / 1,090) − 1, rounded
only at display. These fixture prices are synthetic, not historical market data.
The watchlist's adjusted synthetic close is 14.5 USD/share; missing volume
remains unavailable. Desktop and mobile layouts and local-only browser requests
pass without JavaScript errors. Synthetic screenshots may be inspected in `/tmp`.

## Live research and the correction

Live AAPL USD/XNAS search, instrument identity, raw daily prices, independently
selected adjusted volume, stock volatility/drawdown and accessible charts/tables
passed for August 12–October 9, 2026, with 42 completed sessions. The initial
income check then stopped at an unavailable margin. Intrinio's standardized
income response uses `totalgrossprofit` and `totaloperatingincome`; the margin
calculator and operating-income trends previously expected shorter names.

Both calculators now select the exact supplied total-prefixed tags. This fixes
gross/operating margins and operating-income observations in annual trends.
No amount is reconstructed from revenue/costs and no shorter-name fallback is
introduced. New regressions independently spell the actual tag names and use
conflicting shorter names to prevent synthetic fixture configuration from
masking this mismatch again. Missing inputs still have explicit explanations.

The bounded follow-up exercises AAPL FY2025 margins, FY2025 ROA/ROE with opening
and closing balances, FY2024/2025 revenue/net-income growth, selected-FY basic
and diluted P/E using the October 9 raw close, and two-year income trends.
It independently recomputes each displayed ratio/change from displayed source
observations with Decimal arithmetic, and checks source/version cards, chart
keyboard controls, exact tables, no-store responses and desktop/mobile layouts.
MSFT acceptance identifies an unambiguous USD/XNAS listing; MSFT prices and
fundamentals have not been checked in this milestone.

P/E acceptance exercises the explicit user-confirmed compatibility assumption;
it does not independently verify share class, ADR or split compatibility.
FY2025 earnings with a 2026 price remain a selected-FY comparison, not TTM,
forward, live or historical-as-known P/E. Source versions may contain restatements.
Company market capitalization and both watchlist bases retain their earlier
v0.27/v0.28 live evidence; neither was unnecessarily fetched again here.

The initial attempt used six bounded calls. The successful financial follow-up
uses 26, with its actual backend counter asserted at shutdown: 32 calls across
the two attempts. It skips the already checked AAPL price/detail loads and
previously verified market cap, and checks only Microsoft's listing. No live
values, raw responses or screenshots are saved. Existing vault credentials,
proxy and TLS verification are preserved. No subscription, dependency or
recurring service was added.

## Reproducing the checks

Run from the checkout after the existing frozen setup and local PostgreSQL
helper. System Python supplies the environment's existing Playwright/Chromium;
the server child uses the project's locked Python environment. The browser
database is created by the isolated test role and removed by its owning child.

```sh
export UV_CACHE_DIR=/workspace/.cache/uv
python3 scripts/development_database.py
uv run --frozen --env-file .local/database-test.env python manage.py test --noinput
uv run --frozen ruff check .
uv run --frozen ruff format --check .
python3 tests/browser_release_journey.py
python3 tests/browser_profitability.py
python3 tests/browser_trends.py
```

The live runner is opt-in and requires the already bound Intrinio key. Do not
run it as part of normal startup, installation or secret-free CI. Its default
full coverage has a strict 32-backend-call ceiling, including AAPL market cap
and Microsoft daily prices; that complete default mode was not run this task.
This task's successful follow-up command was:

```sh
python3 tests/browser_live_research.py --financial-follow-up
```

The follow-up ceiling is 26. It is not an automatic retry. The observer wraps
the actual adapter request method without replacing transport or response data;
the ceiling stops an excess call before HTTP. `RequestPacer` waits for the real
10-request client minute window in short intervals. Neither production request
counters nor client addresses are changed. Scripts create no provider cache,
polling or persisted live dataset. After any browser failure, confirm that the
owned child stopped and its temporary database was removed before continuing.

## Validation and remaining work

PostgreSQL: all 957 tests pass without skips, including the two new tag
regressions. SQLite: 957 discovered, 677 pass, 280 PostgreSQL-only checks skip.
Focused margin/trend regression: 69 pass. Ruff lint and format: 194 Python files
pass. The continuous account journey, three synthetic margin scenarios and nine
synthetic trend scenarios pass. Frozen setup is repeatable, migrations have no
drift, Django/static checks and fresh normal application readiness pass.

The six development account/portfolio/journal/correction/watchlist/bookmark
counts stay zero; owned browser databases are removed. Startup forms and
private redirects make no provider request. The original specification checksum
is unchanged. Repository work is local; deployment and remote CI execution have
not occurred.

Two planned release work packages remain for this private MVP:

1. Release safeguards: production settings, CI review, shared request quotas,
   and backup/restore verification. Current quotas are per process and must be
   addressed before multiple workers or wider access.
2. Private deployment: choose a low-cost target, verify its storage/backup and
   applicable Intrinio display/storage rights, then deploy and run smoke checks.

These are work packages, not fixed time estimates. Wider market coverage,
realtime streaming, multi-currency accounting, forecasts and additional advanced
research are separate scope. No production-readiness claim follows from this
acceptance evidence alone.

The subsequent [v0.30 release safeguards](release-safeguards.md) complete the
first work package above. Private deployment is now the remaining planned
private-MVP work package; the v0.29 counts/evidence here remain historical.
