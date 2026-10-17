# Explicit-date portfolio valuation

The private USD valuation page is linked from portfolio details, transaction history and
positions. It uses exact-date raw closes and recorded journal history. Calculations use
the effective journal after [corrections](corrections.md), so historical values can be
restated without reconstructing what was known earlier.

## Load behavior and cost

Choose **View market valuation**, select a completed calendar date in Toronto
time (1900 through yesterday), confirm that recorded shares match the raw price
basis, and submit **Load valuation**. Opening the page makes no provider request.
Submissions are CSRF protected. Quotes are fetched server-side and never stored
or cached; no scheduled polling or real-time feed is added.

A load supports at most five open instruments on the selected date. More than five is
rejected before any quote request. Each instrument uses one daily-price request,
including the security reference supplied by that endpoint; no separate reference lookup
or continuation request is made. A remaining cursor makes that instrument unavailable.
Every request spends the existing shared request budget (10/client and 30 total/minute),
including requests from research pages and journal entry reference lookups. A rate limit
stops remaining instruments and returns 429 with Retry-After. Other provider failures
return a private 503 with fixed messages and unknown affected values. Missing
observations in a valid response return 200 with an explicit incomplete valuation.

These are application request bounds, not verified subscription allowances.
Caching, redistribution/display rights, wider coverage, and shared production
quotas still need verification. Existing Intrinio subscriptions are reused.

## Dates, identity, and share basis

The service takes one bounded, owner-scoped journal snapshot and validates it.
Cash, shares, and remaining FIFO cost include only events dated through the
chosen date, in their existing date/same-day order. Later deposits, sales, and
splits are excluded. A concurrent append after this snapshot cannot change its
cash or quantities while prices load; a subsequent load can include that append.

An accepted price must have the matching stable security ID, explicit USD currency,
and the same supported U.S. MIC as the stored journal label. The requested date,
returned observation date, and snapshot date must match exactly. It must be a
single confirmed daily observation (`intraperiod is False`) with exhausted
pagination, an aware retrieval timestamp, and a finite validated raw close.
Missing currency, changed venue, unconfirmed periods, incomplete responses, or
invalid closes leave that instrument unavailable. Missing raw close never falls
back to adjusted close. An explicit observed zero price is valid and distinct
from missing data.

There is no automatic weekend/holiday fallback, trading-calendar inference,
interpolation, or carry-forward from older prices. Select a date with supplied
confirmed prices. Using an older close with later shares could misvalue a split
or trade, so both sides of the calculation keep the exact chosen boundary.

Recorded splits already change journal shares while preserving lot cost.
Recorded net dividends already enter cash. Adjusted prices could account for
these actions again; valuation therefore uses unadjusted close exclusively.
Manual share-basis confirmation is not automated action discovery or broker
reconciliation. Missing splits can still produce inaccurate results. Current
provider reference metadata is not evidence of historical listing identity or
point-in-time availability, and backdated journal additions can revise results.

## Arithmetic and unavailable values

Calculations use Decimal with explicit precision, independent of caller context.
Each position's market value is shares × raw close, rounded half up once to USD
cents. Its unrealized gain/loss is that value minus remaining FIFO cost, including
capitalized buy fees. Totals sum the displayed rounded position values. Recorded
cash plus all position values gives total value; deposits are not called gains,
and realized gains, dividends, or standalone fees are not added a second time.

If any open position lacks a usable price, aggregate position value, unrealized
gain/loss, and cash-plus-market-value are **Unavailable**. Individually priced
positions remain visible, alongside known cash and cost basis; a partial subtotal
is never presented as the portfolio total. With no open positions, position value
and unrealized gain/loss are zero and total value is recorded cash, with no requests.

Example: deposit $1,000 and buy 10 shares at $25 with a $1 fee. Cash is $749,
FIFO cost is $251. A synthetic confirmed raw close of $15.50 gives $155 market
value, -$96 unrealized gain/loss, and $904 total value. A later 2-for-1 split is
excluded when valuing the earlier date. If the split and a $7 net dividend occur
on or before the selected date, 20 shares at that same hypothetical raw close
give $310 market value, $59 unrealized gain/loss, $756 cash and $1,066 total value.
These are invented arithmetic examples, not market observations.

## Implementation

- `ledger/valuation.py`: immutable result types, quote validity, and pure arithmetic.
- `ledger/analytics.py`: bounded snapshot and optional historical event cutoff.
- `ledger/valuation_services.py`: explicit price loading, instrument cap, safe errors.
- `ledger/valuation_forms.py`, views, URL and template: private date/basis form and tables.
- `market_data/intrinio.py`, `research/services.py`: one-date/one-page adapter and quota.
- Three test modules cover independent dollar examples, the actual HTTPX adapter,
  PostgreSQL snapshots, ownership, CSRF, errors, request limits, and repeat loads.

## Limitations

Valuation uses recorded shares and exact-date raw closes. Missing inputs leave totals
unavailable. Cash-inclusive allocations use the same result. FX, cash-in-lieu, complex
actions and tax reporting are unsupported; this is not brokerage reconciliation.

See [setup and checks](setup.md#automated-checks) and the [methodology
index](methodology.md) for related calculations.
