# Holdings snapshots

A snapshot records user-supplied holdings and explicit USD cash at the close of one
completed U.S. equity session. It is separate from a transaction portfolio. Saving
never creates journal entries, FIFO lots, cost basis, gains or returns. Snapshot
pricing and analysis are not implemented.

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

## Limits and proposed analysis

This format requires users to reshape broker exports. Unsupported instruments,
historical ticker changes and truncated searches may block import. Five holdings
is a deliberate initial capacity, not silent truncation.

A snapshot cannot establish actual account performance or gains. The
[review proposal](proposals/holdings-import.md) specifies future exact-date raw-close
valuation, allocation and concentration. Risk attribution, stress tests and report
exports remain outside the implemented workflow.
