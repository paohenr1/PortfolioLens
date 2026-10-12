# Recorded dividends and stock splits

Version 0.9 extends the immutable USD journal with Dividend and Split entries.
These record the user's supplied actions, not automatically retrieved or verified
company announcements. Existing ordering, owner isolation, CSRF, reference
checks, idempotency, permanent-entry rules and 1,000-entry cap still apply.

## Cash dividends

Choose **Dividend**, use the payment/receipt date and correct same-day order,
enter the security ID and positive **Cash amount (USD)** actually received net
of any withholding. Leave shares, execution price and split terms blank, and
fees zero. Amount accepts two decimal places and the existing 1-trillion-USD cap.

A dividend adds cash and the separate **Net dividends received (USD)** total.
It does not change shares, lot cost, realized sale gain, or contributions.
The total sums only recorded net receipts; it is not gross taxable income,
yield, total return, or verified entitlement. Receipt after selling the position
is allowed: an ex-date holding and a later payment date need not coincide.
No entitlement or ex-date position reconstruction is inferred.

Reinvestment requires a dividend and a separate buy in their correct order;
it is never automatic. Withholding breakdown, return of capital, stock dividends,
negative/clawback payments and tax classification are unsupported. Return of
capital must not be entered as this ordinary cash dividend because it changes
basis under different rules.

## Splits

Choose **Split** on the effective date, supply the security ID, explicit order,
and integer **Split new shares** / **Split old shares**. A 2-for-1 split uses
new=2, old=1; a 1-for-10 reverse split uses new=1, old=10. Each term is between
1 and 1,000,000, and they must differ. Leave amount, trade shares and price blank,
and fees zero. Ratio terms are recorded literally, not normalized for retry
comparison (2:1 and 4:2 are different submitted details).

An open position must exist at this date/order. Each of its open lots changes
remaining shares by new/old. Cash, original total cost, previously allocated
cost and remaining total cost do not change. Later sales use the resulting
share basis; later buys are not affected retroactively by an earlier split.
Other security IDs remain unchanged. Older sale rows retain their original
sale-date quantities and consumed-lot figures.

Share conversions use exact fractions. Both the resulting aggregate position
and each open lot must be positive, exactly representable at six share decimal
places, and no larger than 1 trillion shares. The service never rounds shares
away, rounds them up, invents a cash-in-lieu receipt or changes lot cost. For
example, lots of one and two shares in a 1-for-3 reverse split total one share,
but individual lots would have repeating fractional shares; this is rejected.
Cash-in-lieu and lot consolidation require a separate accounting workflow.

FIFO also scales each lot's original-equivalent share quantity as an exact
fraction, including already-sold shares. This preserves its cumulative cost
allocation after partial sales. Original-equivalent quantity may be fractional
even when the remaining lot has an exact supported quantity. Cents follow the
existing [cumulative FIFO rule](fifo.md); a split itself never realizes a gain.

Example: buy ten at 25 with a 1 fee (251 cost), sell four at 30 with a 2 fee
(100.40 cost, 17.60 gain). A 2-for-1 split changes the remaining six shares to
twelve, retaining 150.60 cost. Selling six at 15 with a 1 fee consumes 75.30
cost and realizes 13.70 gain, leaving six shares with 75.30 cost. Earlier sold
cost is not allocated a second time.

## Validation, reference cost, and migration

All appends now run full FIFO validation before the provider lookup and again
inside the portfolio-row lock. Backdated splits cannot create an invalid later
sale or unrepresentable lot. An exact retry returns the recorded entry without
another lookup or split application; concurrent duplicate submissions apply
once. Different keys at the same date/order conflict. Fresh keys at different
orders can intentionally record multiple actions; this is not deduplication by
company action ID, so review dates/ratios carefully before permanent submission.

A new valid dividend or split uses one bounded instrument-reference lookup via
the existing Intrinio adapter/budget. ID, USD and supported U.S. venue must match;
a changed listing venue is blocked pending reconciliation. Reference retrieval
does not verify the action ratio, dividend amount, payment date, effective date,
historical instrument identity, corporate-action feed entitlement, or completeness.
Provider failure writes nothing. Delisted/unavailable references remain a limit.
Reads, invalid historical balance/lot inputs and exact retries use no requests.

Run the normal migrations, including `ledger.0003_corporate_actions`, with the
development PostgreSQL app configuration. Two nullable ratio columns are added;
old entries remain unchanged. Constraints allow zero amount only for a split,
require valid action/reference shapes, disallow null/zero/equal/out-of-range split
terms, and preserve prior trade rounding/currency checks. The update/delete
immutability trigger remains installed. Populated cash/trade upgrade preservation
is tested on a separate PostgreSQL test database. Rolling back after action rows
exist needs an explicit data-preservation plan; do not delete them to make a
schema downgrade succeed.

## Verification and next part

```sh
export UV_CACHE_DIR=/workspace/.cache/uv
uv run --frozen --env-file .local/database.env python manage.py migrate --noinput
uv run --frozen --env-file .local/database-test.env python manage.py test --verbosity 2
python3 tests/browser_actions.py
```

This part adds 13 pure accounting and 11 real PostgreSQL storage/race/migration
tests. The full PostgreSQL suite passes 518 tests without skips. The full SQLite
run skips 216 PostgreSQL tests; it does not establish private storage readiness.
Browser tests use an owned temporary PostgreSQL database with synthetic instrument
reference transport and manually entered example events. They check dividend
cash, forward/reverse splits, preserved FIFO basis, exact retries, fractional
rejection, owner isolation, sign-out, keyboard tables and desktop/mobile layouts.
They remove the child server/database and write no development records or live
provider calls. Screenshots: `/tmp/stock-actions-*.png`.

No dependency or paid service was added. [Market valuation and unrealized gains](valuation.md)
now use prices on the same recorded share basis and explicit as-of dates/missing-data
states. [Allocation weights](allocations.md) use complete inputs, and [time-weighted
performance](performance.md) supports confirmed end-of-day flows. Private [watchlists](watchlists.md) are implemented. Explicit [corrections](corrections.md) are implemented. Bounded [daily session returns](daily-returns.md) are implemented. Observed [volatility and drawdown](risk.md) are implemented. Next: benchmark comparison with aligned sessions. Manually recorded actions do not prove that all
historical actions are present. Mergers, spin-offs, cash-in-lieu, return of capital,
transfers, FX and tax adjustments remain unsupported. Money-weighted
and annualized returns remain pending; dividend-adjusted price series must not be combined
with separately credited dividends to count income twice.
