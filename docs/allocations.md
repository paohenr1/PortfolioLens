# Cash-inclusive allocation weights

The private valuation page includes cash-inclusive allocation weights. Choose **View
market valuation**, select a completed date, confirm recorded share basis, and submit
**Load valuation**. Weights use the same valuation snapshot and prices without
additional provider requests or database writes.

Calculations use the effective journal after [corrections](corrections.md). Historical
results can be restated; the audit does not reconstruct what was known earlier.

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

## Implementation

`ledger/allocations.py` contains immutable rows/results and the pure calculator. The
existing valuation view passes its completed result to that calculator and renders a
keyboard-accessible allocation table. The calculator does not persist a projection or
request prices.

## Limitations

Weights describe recorded cash and holdings. They do not infer sector exposure, fund
look-through, target allocations, rebalancing, FX or tax adjustments. Complete manually
recorded transactions and splits are required.

See [setup and checks](setup.md#automated-checks) and the [methodology
index](methodology.md) for related calculations.
