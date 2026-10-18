# Holdings snapshots

A snapshot records user-supplied holdings and explicit USD cash at the close of one
completed U.S. equity session. It is separate from a transaction portfolio. Saving
never creates journal entries, FIFO lots, cost basis, gains or returns. An explicit
review can load dated raw closes to show value, allocation and concentration.

## Input and reference validation

Use **Check a holdings CSV** from **My portfolios**, or **Import a holdings CSV**
from **My holdings snapshots**. The [usage guide](usage.md#check-a-holdings-csv)
describes the exact CSV format. Limits are 16 KiB, five holdings, supported U.S.
MICs, positive quantities through one billion with six decimals, and explicit USD
cash through one trillion with two decimals. A header-only file requires positive
cash. Dates must be completed XNYS sessions from 2000 through yesterday in Toronto.

Checking is local and transient. **Find instrument matches** performs one search
per unresolved row, at most five requests. Only exact ticker/MIC/USD candidates
are offered. A bounded full search page, remaining cursor, absent match or more
than five exact candidates leaves the row unresolved. No case/venue substitution
or manual provider-ID bypass is accepted. Select each instrument explicitly, even
when only one is offered.

**Validate selections** makes one reference request per selected ID, up to five.
ID, ticker, MIC, USD and aware retrieval time must agree with the input contract.
Duplicate resolved IDs are rejected. Current reference metadata cannot prove
historical identity, ticker continuity or broker reconciliation. Provider failures
preserve the preview; a rate-limit response stops further requests and displays a
retry delay. Retrying is explicit and uses the normal shared request budget.

Before saving, confirm that quantities and cash describe the selected date's close,
include effective trades/splits, and use the raw share basis. This records the
user's assertion, not independently verified historical holdings.

## Storage and privacy

PostgreSQL stores separate `HoldingsSnapshot`, `SnapshotHolding` and
`SnapshotSubmission` records. An additive migration creates these tables without
changing transaction history. Snapshots contain the name, date, USD cash,
confirmation version, creation time, exact quantities, stable instrument IDs,
minimal reference labels and retrieval timestamps. No raw uploads, prices,
calculated values or reports are stored.

Workflow state is signed, bound to the active account, capped at 128 KiB and expires
15 minutes after the original CSV preview. Each transition and save revalidates
its schema, inputs and stage. Re-signing never extends the original deadline.
State is carried in POST forms, not URLs or session blobs. Private responses use
no-store; forms use CSRF and escape user/provider text.

The application has no snapshot edit operation. Correct inputs through a new
import. Only the owner can list, view or confirm deletion; foreign/missing IDs
return the same 404. Deleting removes the snapshot and its holdings, with no effect
on journal entries or transaction portfolios.

Saves lock the active owner row, recheck expiry and capacity, then write all rows
atomically. An owner can keep 50 snapshots. A submission key is unique per owner:
identical normalized selected inputs return the original snapshot, while conflicting
inputs fail. A fresh key permits a separate snapshot with the same contents.
Database constraints protect numeric ranges, USD denomination and instrument/key
uniqueness; service validation enforces date policy and the five-holding limit.

Deletion leaves only the owner, submission key, input digest and original expiry in
a receipt until that preview expires, preventing a stale retry from restoring the
snapshot. Subsequent owner writes remove expired deletion receipts. No scheduled
cleanup is required. Live snapshot receipts retain retry identity while the snapshot
exists. Provider calls happen outside database locks; save/delete/view make none.

## Limits

This format requires users to reshape broker exports. Unsupported instruments,
historical ticker changes and truncated searches may block import. Five holdings
is a deliberate initial capacity, not silent truncation.

A snapshot cannot establish actual account performance or gains. Risk attribution,
stress tests and report exports remain outside the implemented workflow. The
[workflow specification](proposals/holdings-import.md) records the bounded design.


## Review methodology

**Load snapshot review** requires an owner-authenticated, CSRF-protected POST. The
saved date, cash and holdings are copied consistently under an owner-row lock;
the lock is released before provider I/O. Stored input limits and the completed
session policy are revalidated before spending quota. The result is withheld if
the snapshot is deleted or the owner is disabled during the load.

Each holding consumes one daily-price request through the existing shared
10-per-client/30-global per-minute admission. There is no separate reference
request, pagination follow-up, automatic retry, GET-triggered request or cache.
A 429 stops the remaining holdings and returns Retry-After; other provider failures
return 503 with safe fixed messages and preserve individually known values.
A missing/invalid observation without a transport failure yields an incomplete
review with status 200. Cash-only inputs make no price requests.

A usable observation follows `ledger.valuation.confirmed_close`: exact stable ID,
stored MIC, explicit USD, requested/returned date, one confirmed completed daily
observation, exhausted pagination, aware retrieval time and a finite bounded raw
close. Adjusted, prior or later closes never substitute. Zero is a valid observed
price and is distinct from missing. Retrieval times describe data access, not
exchange quote timestamps or historical identity evidence.

```text
holding value = quantity × raw close, rounded half up once to USD cents
holdings value = sum of those rounded values
total value = holdings value + supplied cash
component weight = component value / total value × 100
```

Arithmetic uses Decimal with explicit precision. Allocation converts values to
integer cents and uses the same largest-remainder basis-point policy as
[transaction portfolios](allocations.md): floor each percentage to 0.01 points,
then distribute residual points by remainder, with cash first and stable IDs next
for exact ties. Available weights reconcile to 100.00%. A small positive value
can display 0.00%.

Concentration ranks holdings by cent value, breaking ties by stable ID. Cash is
excluded from the ranking but included in total value. Largest-holding and
largest-three percentages use their combined cent values divided directly by the
total, rounded half up to two decimals. With fewer than three holdings the latter
includes all holdings. Do not sum rounded allocation percentages: with four
USD 1 holdings and USD 2 cash, the first three displayed weights can sum to
50.01%, but direct top-three concentration is 50.00%.

If any holding is unpriced, holdings/total value and every weight/concentration
ratio are unavailable. Known cash and row values remain visible. The count of
priced holdings is not value coverage and a subtotal is not the total. A complete
zero-value result retains its observed zeros but has undefined ratios. Positive
cash-only snapshots have 100.00% cash weight; holding concentration is not applicable.

For example, synthetic holdings of 10 shares at USD 20 and 5 shares at USD 40,
plus USD 100 cash, give USD 500 total, 40%/40% holding weights, 20% cash weight,
40% largest-holding concentration and 80% top-three concentration. No cost basis,
gains, returns or risk scores follow from these inputs.

Implementation: `portfolios/snapshot_review.py` is pure arithmetic;
`snapshot_review_services.py` owns private input reads and bounded I/O;
`snapshot_review_views.py` renders the explicit-load page. Only the reusable
allocation arithmetic is shared with `ledger/allocations.py`; snapshots never
manufacture FIFO/cost-basis objects. Existing journal valuation remains separate.
