# FIFO positions, cost basis, and realized sale gains

Open **View positions and gains** from portfolio details or transaction history. The
private page displays recorded cash, remaining FIFO cost basis, realized sale
gains/losses, standalone fees, open positions and every sale, including sales of fully
closed positions. Expand a row to inspect open or consumed lots.

All money is USD. Open quantities include explicitly recorded splits; sales retain their
date/order share basis. See [dividends and splits](corporate-actions.md). Calculations
use the effective journal after [corrections](corrections.md), so historical results can
be restated without reconstructing what was known earlier.

## Calculation policy

First in, first out (FIFO) is the initial research accounting method. Events sort
by transaction date and explicit same-day order, independently of submission
order. Security IDs define separate lot queues; ticker renames do not create a
new position. Each buy creates a lot with original quantity and cost equal to its
rounded gross execution value plus buy fees. Sales consume the oldest available
shares for that ID, proceeding to later lots when necessary.

A sale's net proceeds are its rounded gross execution value minus sell fees.
Its realized gain/loss is net proceeds minus the FIFO cost allocated to its sold
shares. Losses retain their negative sign. Buy fees and sell fees enter once;
standalone Fee entries reduce cash and appear separately, without changing sale
gain. Deposits and withdrawals affect cash, not FIFO gain. Zero realized gain
when no sales exist is a computed journal result, not a substituted market value.

The existing ledger rounds each trade notional to cents once, half up. FIFO uses
Decimal for quantities/money and exact standard-library Fraction arithmetic for
proportional cents, avoiding division precision changing half-cent ties. The
allocation rule for a particular lot is:

1. Cumulative allocated cost = original lot cost × cumulative shares sold ÷
   original shares, rounded half up to cents.
2. Cost assigned to the current sale = new cumulative allocated cost minus
   previously allocated cost.
3. Remaining lot cost = original lot cost minus cumulative allocated cost.

This preserves original cost exactly. Closing the lot allocates its entire
remaining cost; splitting sales does not change cost allocated at the same
cumulative sold quantity. Individual sale proceeds still follow the journal's
per-trade rounding, so changing execution batching can change proceeds. Very
small residual lots can have zero cent-denominated basis. An average unit price
is not calculated or rounded before allocating cost.

For example, a three-share lot costing 0.04 USD allocates costs of 0.01, 0.02,
then 0.01 across three one-share sales. Rounding each independent third to 0.01
would lose a cent; cumulative allocation preserves all four cents.

## Independently calculated examples

The earlier journal example deposits 1,000, buys 10 at 25 with a 1 fee, sells 4
at 30 with a 2 fee, withdraws 100, and pays a standalone 3 fee. Recorded cash is
764. The buy lot costs 251; four-tenths allocates 100.40 to the sale. Net sale
proceeds are 118, realized gain is 17.60, and six shares retain 150.60 cost basis.
The standalone fee is shown as 3, separate from that sale gain.

A multi-lot example deposits 1,000, buys three shares at 10 with a 1 fee (lot
cost 31), buys two at 20 with a 2 fee (lot cost 42), then sells four at 30 with
a 3 fee. FIFO allocates the full first lot's 31 plus half of the second lot's 42:
52 cost, 117 net proceeds, and 65 gain. One share remains with 21 cost. Cash is
1,044; this cash figure is not a portfolio valuation. Selling the remaining
share at 10 with a 1 fee realizes a 12 loss. No positions remain; total realized
gain is 53, open cost is zero, and recorded cash is 1,053.

## Snapshot, ownership, and display rules

The pure calculator is [ledger/fifo.py](../ledger/fifo.py), with no Django,
database, clock, or provider dependency. It validates USD/event/precision rules
and every historical cash/share prefix before deriving immutable output tuples.
It does not modify the input journal. The read service also checks the Toronto
date ceiling and reads at most 1,001 rows to enforce the 1,000-entry limit.
Invalid, future, or oversized direct-insert journals return a private HTTP 503
calculation-unavailable page; no misleading totals are displayed.

The page is sign-in-only and GET-only. Its portfolio lookup filters by the
signed-in owner before loading entries. Foreign/missing IDs share a generic
private 404, forged owner/query IDs have no effect, and responses including
routing/errors are no-store. The service uses two database queries regardless
of the number of lots. It makes no provider calls and saves no projection rows.
Existing journals remain readable when the provider key is unavailable.

Open positions sort by stable ID, sales by date/order. Each table paginates
independently at 25 rows; totals always include the full bounded snapshot, and
pagination links preserve the other table's page. A later valid backdated buy
or sale can change subsequent FIFO allocations: these are rebuilt calculations,
not locked historical tax results. Concurrent appends after the entries query
appear on the next request; every figure in this response uses one entries list.

Labels use the newest stored instrument-reference retrieval timestamp (submission
time breaks ties). Open positions display that timestamp. Sale-row labels also
use this latest journal label, not a reconstructed ticker as of the sale date.
Labels are HTML-escaped; no quote or current reference refresh occurs.

## Limitations

These are research accounting results, not brokerage reconciliation or a tax statement.
No specific-lot selection, short positions, FX or tax adjustments are supported. Market
valuation and returns are separate calculations.

See [setup and checks](setup.md#automated-checks) and the [methodology
index](methodology.md) for related calculations.
