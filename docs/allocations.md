# Cash-inclusive allocation weights

Version 0.11 adds allocation weights to the existing private valuation page.
Choose **View market valuation**, select a completed date, confirm recorded share
basis, and submit **Load valuation**. The allocation table uses that same valuation
snapshot and prices. It makes no additional provider request or database write.
Opening the form does not fetch prices or display claimed weights.

Version 0.14 uses the current effective journal after explicit
[corrections](corrections.md). Historical event-date results can be restated; the
audit preserves original entries but does not reconstruct what was known earlier.

## Basis and availability

The denominator is recorded cash plus all position market values on the selected
date, in USD. Each component's weight is its value divided by that total, expressed
as a percentage. Cash is included as its own component; holdings use stable security
IDs and stored reference labels, rather than aggregating potentially reused tickers.
Remaining cost basis is not the allocation basis. Deposits and recorded dividends
can change cash and weights; weights do not measure investment returns.

All weights require a complete valuation with positive total value. If a price is
missing or the provider fails, every weight, including cash's, is **Unavailable**.
Known component values remain visible, but there is no partial denominator or
allocation inferred from the priced subset. Existing price/date, instrument,
currency, venue and share-basis checks still apply; see [valuation policy](valuation.md).

A cash-only portfolio with positive cash has a 100.00% cash weight and needs no
quote requests. An empty portfolio, or zero cash with only zero-priced holdings,
has zero total value and undefined weights. A valid zero-priced holding has 0.00%
weight when the total is positive; zero is not a replacement for a missing price.
Negative, nonfinite, non-cent or unreconciled component amounts cannot produce
weights. This remains the journal's long-only, nonnegative-cash USD model.

## Reconciled rounding

Weights display two decimal places. Independent rounding can yield 99.99% or
100.01%, so the pure calculator uses the largest-remainder method in integer
basis points (one point equals 0.01 percentage points): start with each weight
rounded down, then distribute remaining points to the largest fractional
remainders. Exact ties go to cash first, then ascending stable security IDs.
Cash appears first and holdings follow that ID order, independently of input order.

The displayed percentages sum to exactly 100.00% whenever weights are available.
Each differs from the unrounded value by less than 0.01 percentage points.
A small positive component may display 0.00%; its actual USD value remains visible.
Amounts are checked using exact Fraction arithmetic, and percentage formatting
uses an explicit Decimal context so caller precision cannot change the result.

Examples, using invented amounts:

| Cash | Holding values | Displayed weights (cash first) |
| --- | --- | --- |
| $100 | $100, $200 | 25.00%, 25.00%, 50.00% |
| $1 | $1, $1 | 33.34%, 33.33%, 33.33% |
| $749 | $155 | 82.85%, 17.15% |
| $55 | None open | 100.00% |
| $0 | None open | Unavailable: zero total |
| $100 | Missing price, $200 | All weights unavailable |

These are arithmetic examples, not real market observations or recommendations.

## Modules and verification

`ledger/allocations.py` contains immutable rows/results and the pure calculator.
The existing valuation view passes its completed result to that calculator and
renders a keyboard-accessible allocation table. No new route, persisted projection,
dependency, migration, paid service, scheduled task or price request is added.

This part adds 21 tests: 14 pure calculations and seven real PostgreSQL page tests.
They cover dollar examples, exact ties, component-order independence, small/zero
holdings, incomplete/invalid amounts, empty/cash-only portfolios, privacy and
unchanged request/journal counts. Two hundred deterministic generated cent-value
examples also check exact totals, weight bounds and maximum rounding error.

Full PostgreSQL suite: **518 passed, no skips**. Full SQLite: 518 discovered,
302 passed and 216 PostgreSQL tests explicitly skipped; SQLite does not verify
private portfolio storage. Ruff lint/format, Django system checks, migration drift
and static collection pass. Expanded valuation and existing FIFO desktop/mobile
browser checks pass with explicitly synthetic data on isolated PostgreSQL databases.
They verify tables, weights, empty/partial states, historical cutoff, keyboard
access, owner denial, CSRF and sign-out. Screenshots: `/tmp/stock-allocation-*.png`
and `/tmp/stock-valuation-*.png`. Temporary test processes/databases are cleaned up;
development users, portfolios and entries remain unchanged. No live API calls ran.

From the repository root:

```sh
export UV_CACHE_DIR=/workspace/.cache/uv
uv run --frozen --env-file .local/database-test.env python manage.py test --noinput
python3 tests/browser_valuation.py
```

These are value weights of recorded holdings and cash. Sector/asset-class exposure,
fund look-through, target allocations, rebalancing, FX, short positions, investment
return percentages from weights and tax adjustments are not inferred. Completeness still depends on manually
recorded transactions/splits. Live valuation, broader coverage, display rights,
distributed quotas and production deployment remain unverified or incomplete.
[Time-weighted performance](performance.md) is implemented separately with explicit
periods and confirmed end-of-day cash-flow timing. Private [watchlists](watchlists.md) are implemented. Explicit [corrections](corrections.md) are implemented. Bounded [daily session returns](daily-returns.md) are implemented. Observed [volatility and drawdown](risk.md) are implemented. Next: benchmark comparison with aligned sessions.
