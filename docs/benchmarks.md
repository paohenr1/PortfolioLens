# Benchmark comparisons

Version 0.17 adds an optional benchmark to **View daily returns**. Find an
instrument through **Search stocks**, open its details, and copy its **Provider
instrument ID** into **Optional benchmark security ID**. Choose completed session
dates, confirm the existing flow/share-basis conditions, and **Load daily returns**.
Leave the benchmark blank for the existing portfolio-only workflow.

The selected security must use USD and a supported U.S. equity venue. There is
no assumed default, ticker substitution, currency conversion, automatic load or
refresh. GET requests show the form without market-data requests. Loads require
an authenticated owner and CSRF-protected POST. Prices and comparisons are
request-local; no new table, persistent quote cache, dependency or paid service
was added. The original product specification remains unchanged.

## Definitions and comparison basis

The portfolio uses its existing corrected-journal daily time-weighted return:

```
portfolio factor = (ending value − net end-of-day external flow) / opening value
benchmark factor = current provider-adjusted close / previous provider-adjusted close
cumulative return = (product of unrounded factors − 1) × 100
gap in percentage points = portfolio cumulative return − benchmark cumulative return
```

Fractions preserve exact input values and factors until final Decimal display
rounding to four places. The gap uses unrounded factors, rather than subtracting
displayed percentages. For example, a portfolio going 100 → 110 → 99 returns
−1%; a benchmark adjusted-price series 50 → 55 → 60 returns +20%; their gap is
−21 percentage points. It is not a relative wealth ratio, alpha or annualized
outperformance.

External portfolio funding never enters benchmark returns. Portfolio returns
include recorded dividends and fees and use raw prices matching recorded shares.
The benchmark uses the provider's adjusted closes; it has no journal cash flows
or portfolio trading fees. Raw prices are never substituted for missing adjusted
closes. Provider adjustment methodology, reinvestment assumptions and index
tracking have not been independently verified. The page therefore labels this
as an **adjusted-price proxy**, not an audited total-return index. An ETF chosen
as a proxy is still that security, not its underlying index. The user's U.S. EOD
Index Levels plan remains a candidate for later work after endpoint, entitlement
and methodology verification.

## Matching and unavailable results

The [daily planner](daily-returns.md) supplies every consecutive NYSE session in
the completed 90-calendar-day range, including the opening baseline. Benchmark
observations must match those exact dates in chronological order, one per
session. Identity, USD currency, supported reference venue, reference/history
venue agreement, requested range, complete pagination and aware retrieval times
must match. Every close must be confirmed by `intraperiod=False` and have a
finite, bounded Decimal adjusted price. No weekend rows, duplicate dates,
extra observations, missing sessions, earlier-close fills or dropped rows are
accepted.

All comparison metrics and its chart are unavailable when either required series
is incomplete or inconsistent. Available endpoints cannot bridge a missing
middle session. A positive opening price is required for every benchmark return;
a terminal zero is a valid total loss, while an intervening zero followed by a
restart is undefined. The portfolio's own return, risk and provenance remain
visible when only benchmark data fails. Safe provider errors retain existing
503/429 behavior and `Retry-After` handling. A rate limit stops later requests.

## Limits, snapshot and presentation

The comparison reuses the daily producer's one materialized effective journal
snapshot. Its two database reads occur before provider I/O. Corrections therefore
restate this calculation consistently; a concurrent edit is reflected on a
subsequent load, not by rereading midway through this action.

The portfolio keeps its two-instrument, four-pages-each ceiling and 16 cash-flow
boundary limit. Preflight validation occurs before benchmark reference requests.
Optional comparison adds at most one reference request and one price request,
for **ten provider requests maximum per action**. Every request spends the shared
process budget; recent actions may exhaust it before this maximum. Benchmark
prices use one page of up to 100 rows. A remaining cursor stays incomplete and
is never followed. If the benchmark is an already loaded portfolio instrument,
that history is reused without another price request. Cash-only portfolios load
only the optional benchmark's reference and prices; blank selection adds nothing.

The chart shows cumulative percentage returns from 0% at the opening close,
using calendar spacing. A solid portfolio line and dashed benchmark line share
the same scale. Pointer/touch inspection and focused-point Left/Right/Home/End
controls show both exact displayed values and their gap. An accessible scrolling
table provides daily returns, cumulative returns, adjusted prices and gaps.
Coordinates are display-only. Provenance shows reference and history retrieval
times, which do not establish quote freshness or adjustment methodology.

## Validation and remaining work

42 new tests cover independent arithmetic, funding, rounding, exact alignment,
missing/invalid prices, metadata consistency, terminal loss/restart, chart bounds,
pure imports, private ownership, CSRF, snapshot reads, no writes, preflight,
safe failures, missing credentials and real mock-HTTP quota/pagination behavior.
The adapter transport demonstrates eight portfolio pages plus one benchmark
reference and one benchmark page, spending exactly ten budget units.

Full PostgreSQL: **739 passed without skips**. SQLite: **484 passed, 255 skipped**;
SQLite does not validate PostgreSQL storage/concurrency. The benchmark browser
passes on desktop/mobile in a disposable PostgreSQL database with synthetic
prices, covering cash/funding, exact +30% benchmark and −25.1400-point gap,
missing data, chart keyboard/touch behavior, table access, ownership and CSRF.
Existing daily, risk and price-chart browser checks also pass. Ruff checks 133
Python files; Django, migration-drift and static-collection checks pass.

```sh
uv run --frozen --env-file .local/database-test.env python manage.py test --noinput
python3 tests/browser_benchmarks.py
```

No live API request was needed for this module. Live benchmark acceptance,
index methodology, coverage/licensing and production deployment remain unverified.
[Correlation and beta](relationships.md) are implemented. [Sharpe](sharpe.md) is implemented. [Selected-period profitability](profitability.md) is implemented. [Annual return on assets/equity](capital-returns.md) is implemented. [Annual revenue and earnings growth](growth.md) is implemented. Next: valuation multiples with explicit price and earnings dates.
