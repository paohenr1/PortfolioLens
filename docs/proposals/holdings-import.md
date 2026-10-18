# Holdings import and dated snapshot review

Status: CSV validation/preview, explicit instrument resolution and private snapshot
persistence and dated value/allocation/concentration review are implemented. This
document defines the bounded workflow within PortfolioLens's existing Django/PostgreSQL
application. Current transaction-based
portfolios and their limits remain as described in [product scope](../product-specification.md).

The current **Check holdings CSV** tool validates metadata and file structure only.
Checking alone does not resolve instruments, write business records or fetch prices.
Users can then explicitly continue to matching, reference verification and confirmed
saving. See [current snapshot behavior](../holdings-snapshots.md).

## Outcome and boundary

A signed-in user can supply a small holdings CSV, resolve instruments, confirm an
as-of date and cash balance, and save a private snapshot. An explicit analysis
load shows dated market value, allocation/concentration and input-quality findings.
The on-screen review also supports browser printing/PDF saving. Server-generated
report files remain outside this workflow.

A snapshot records supplied holdings at one date. It does not create deposits,
buys, lots, trades, corrections or other journal entries. It cannot establish
cost basis, realized/unrealized gains, time-weighted returns, account performance,
volatility, beta or Sharpe. Do not manufacture a zero cost basis or infer purchases
at the snapshot date to reuse existing ledger calculations.

Initial scope is USD cash and long holdings on the U.S. equity venues already
supported by `market_data/venues.py`, with at most five unique instruments. This
keeps the first valuation load within five exact-date price requests. The separate
transaction-based daily-return workflow retains its two-instrument/90-day limit.

Broker-specific formats, spreadsheets/PDFs, transaction imports, shorts, options,
FX, historical snapshot comparisons, sector/fund look-through, risk attribution,
stress tests, recommendations and server-generated report exports are outside this slice.

## Input contract

Use one CSV template, with no automatic column guessing. The upload contains
holdings only; the form supplies snapshot name, date, USD cash and confirmation.

| Input | Rule |
| --- | --- |
| Name | Required, 1–100 characters after trimming; no control characters |
| As-of date | Required completed XNYS session, from 2000 through yesterday in America/Toronto; no default that implies the holdings date is known |
| Cash | Required explicit USD amount, 0 through 1,000,000,000,000, at most two decimals; blank is not zero |
| File | UTF-8 (optional BOM), comma-delimited, one header; at most 16 KiB and five nonblank data rows |
| Header | Exactly `ticker,exchange_mic,quantity,currency`, in this order |
| Ticker | Required bounded text, at most 32 characters; retain punctuation and case; reject formula prefixes (`=`, `+`, `-`, `@`) and literal quotes |
| Exchange MIC | Required explicit code in the existing supported-venue set |
| Quantity | Positive finite decimal, at most 1,000,000,000 shares and six decimals |
| Currency | Required literal `USD` |

Trim surrounding field whitespace. Accept plain decimal digits with an optional
fraction (at most 32 characters per numeric input); reject signs, exponents,
thousands separators, formulas, NaN/infinity,
excess precision, malformed quoting, extra/missing columns and embedded control
characters. Empty lines may be ignored; every nonblank row must validate. Reject
zero-quantity rows rather than silently discarding them. A header-only file is
valid for cash-only holdings when explicitly entered cash is positive.

Reject duplicate ticker/MIC rows at parsing and duplicate resolved provider IDs
before saving. Do not silently combine rows or import only a valid subset. Errors
identify the row and field without exposing raw uploads in logs. Enforce limits
while reading the stream, not after materializing an arbitrarily large file.

The form must require this confirmation before saving:

> These quantities and the cash balance describe my holdings at the close of the
> selected date. Quantities include trades and splits effective by that date and
> match the raw share basis. This is a holdings snapshot, not transaction history.

This is a user assertion, not independent broker reconciliation. Current reference
metadata cannot prove historical identity. Keep that limitation in the review.

## Preview, resolve and save

1. **Upload and validate:** parse locally on the server, show normalized rows and
   all validation errors. No provider requests or business-record writes occur.
2. **Find instrument matches:** on explicit submission, run one bounded existing
   search per unresolved row, at most five calls per action. Show only exact
   ticker/MIC matches returned by that search. More than five exact candidates per row remains unresolved. Each choice includes stable provider
   ID, name, MIC and currency. Require explicit selection even for one candidate.
3. **Validate selections:** on explicit submission, retrieve each selected stable
   ID once, at most five calls. Require exact ID, ticker/MIC and USD agreement.
   Reject substitutions, mismatches, unsupported references and duplicate IDs.
   A truncated search or absent exact match is unresolved, never guessed.
4. **Confirm and save:** show date, cash, quantities, resolved references and
   warnings together. Persist all rows atomically only after confirmation.
5. **Load snapshot review:** request dated prices only after an explicit action on
   the saved snapshot. Viewing the saved inputs makes no provider requests.

Ticker renames, historical ticker ambiguity or references that cannot be resolved
leave import blocked with an explanation. No manual unverified provider-ID bypass
is included. The resolver uses the existing backend adapter and safe error policy.

Use a bounded, expiring, user-bound signed preview payload (lifetime:
15 minutes) carrying validated inputs and references. Validate structure, scope,
age and confirmation again on save. Recheck all non-provider invariants before
writing. An expired or changed preview requires revalidation; possession of a
signature is not authorization for another user's records. Raw uploads are not
stored as files, session contents or database blobs.

A client submission key is unique per owner. The same key and canonical normalized
inputs return the original saved snapshot; different inputs with the same key are
rejected. A new key creates a separate snapshot even for identical holdings, with
no content-based deduplication across accounts. Concurrent retries create one row
set. Generate a fresh key for a new import, including after deletion.

## Review contents and financial definitions

Title the result **Holdings snapshot review · YYYY-MM-DD**. Always show the snapshot
date, USD denomination, source, retrieval time, raw-price basis, input confirmations
and available/unavailable status. Never label the result account performance.

For each instrument show quantity, confirmed raw close, market value and total-value
weight. Show cash separately. Keep the snapshot date fixed when prices are loaded;
no weekend/holiday fallback or use of today's prices for older holdings.

Accepted prices follow `ledger.valuation.confirmed_close`: exact instrument, MIC,
USD currency and date; one confirmed completed observation; exhausted pagination;
aware retrieval timestamp; finite bounded raw close. Observed zero remains distinct
from missing. Adjusted or prior closes never substitute for unavailable raw prices.

```text
holding value = quantity × raw close, rounded half up once to USD cents
holdings value = sum of the rounded holding values
total value = holdings value + explicitly supplied cash
weight = component value / total value × 100
```

Use Decimal with sufficient explicit precision and no binary floats. Allocation
weights include cash. Reconcile displayed weights to exactly 100.00% using the
existing integer-basis-point largest-remainder policy: cash first, then stable ID
for ties. Do not introduce a fabricated FIFO object to call the existing API.

The first concentration summary contains:

- Cash weight.
- Largest holding's share of total value.
- Largest three holdings' combined share of total value (all holdings if fewer).
- Holding count and individually priced count.

Rank holdings by their cent values, breaking ties by stable provider ID. Compute
concentration percentages directly from cent totals, then round half up to two
decimals; do not sum previously rounded individual weights. Cash is excluded from
holding rankings but included in the denominator. Display those definitions. Do
not turn these descriptive values into risk scores or suitability advice.

If any holding lacks a usable price, preserve known individual values and cash
but withhold aggregate holdings/total value, all weights and concentration ratios.
Show each missing/invalid observation explicitly. A partial subtotal is not the
portfolio total; a count of priced rows is not value coverage.

Cash-only snapshots need no price requests: total equals cash, cash weight is 100%,
and holding concentration is not applicable. For a complete all-zero valuation,
total value is zero and percentages are unavailable, never divided by zero.

Example with explicitly synthetic values: 10 shares at USD 20, 5 shares at USD 40,
and USD 100 cash give USD 500 total, 40%/40% holding weights, 20% cash weight,
40% largest-holding concentration and 80% combined concentration. If either price
is missing, total value and all these percentages are unavailable.

## Persistence, privacy and request limits

Separate owner-scoped snapshot and holding models use the existing
`portfolios` app, with additive migrations. Stored fields include owner, UUID,
name, as-of date, explicit USD cash, confirmation/schema version, creation time,
submission key/input digest, and normalized holdings with stable IDs and reference
retrieval timestamps. Store only the minimal selected reference fields already
used by portfolios/watchlists, subject to applicable data-use rights.

Snapshots are immutable after confirmation. Correct input by importing a new
snapshot; do not change an existing journal or silently replace a saved snapshot.
Provide owner-only confirmed deletion of a snapshot and its own holding rows,
without affecting transaction portfolios. Initial capacity is 50 snapshots per
owner, enforced under an owner-row lock and checked again at save. Reuse of a
removed snapshot's submission key must fail as an expired/consumed submission;
retain a minimal owner/key/digest tombstone without holdings until the original
preview expires to enforce that rule. Expired tombstones can be removed during
subsequent owner-scoped writes; no scheduled cleanup service is required.

Use database constraints for duplicate IDs within a snapshot, supported numeric
ranges and USD currency, plus transactional service validation for the five-row
limit and date policy. All routes require active authentication; foreign/missing
IDs give the same private 404. Mutations use CSRF-protected POST and no-store
responses. Escape filenames, row text and provider labels. Do not log raw uploads,
private holdings, signed payloads, credentials or authenticated URLs.

No price response, calculated valuation or report artifact is persisted in this
slice. Repeat analysis retrieves prices again and can reflect provider corrections;
the saved input is immutable but the calculated result is not a frozen report.

All provider calls use the existing 10-per-client/30-global per-minute admission
budget. Search, reference verification and pricing are separate explicit actions,
not separate quota allowances. A 429 stops remaining requests and shows Retry-After;
provider failure preserves input/error context without silently retrying. Any retry
is explicit and consumes the normal budget. No GET-triggered calls, batching that
bypasses quotas, background jobs, caches or paid services are introduced.

## Integration and implementation slices

1. Add the strict parser, pure input contracts and row-level preview errors with
   independent fixtures. Keep parsing free of provider/database I/O.
2. Add explicit instrument resolution, private immutable snapshot storage,
   idempotent save/deletion and ownership/concurrency checks. Keep the feature
   clearly labeled as saved inputs until analysis exists.
3. Add bounded exact-date pricing and a pure snapshot-value/allocation calculator,
   then the on-screen review and input-quality findings.

Reuse validated provider contracts, date/session helpers, request budgets and
numeric policies. Existing valuation types include FIFO basis/gains and are not a
suitable snapshot contract. Prefer a small separate typed result; extract shared
arithmetic only where equivalence is demonstrated by existing and new tests.
Existing journal, valuation and daily-return routes must remain unchanged.

## Acceptance criteria

- Invalid, oversized, duplicate, ambiguous and unsupported input causes no partial
  save; parse failures spend no provider requests.
- Explicit zero cash is accepted; blank cash, negative/nonfinite numbers and excess
  precision are rejected. Fractional shares are preserved exactly.
- Reference mismatches, tampering, stale previews, cross-user IDs and inactive
  accounts cannot save or reveal holdings. Signed fields are not treated as trusted
  merely because they originated in a previous form.
- Concurrent identical saves create one snapshot; conflicting keys and capacity
  races fail safely. A deleted snapshot cannot be resurrected by a stale retry.
- Independent arithmetic tests cover rounding/ties, cash-only, zero value, missing
  raw closes, adjusted-only data, wrong dates/currency/MIC and provider failures.
- Request-count tests enforce each action's ceiling and shared admission. Rate
  exhaustion stops further calls and never substitutes fixtures or old prices.
- PostgreSQL and two-user browser tests cover isolation, CSRF, atomicity, retries,
  deletion, desktop/mobile layout and keyboard access using synthetic inputs.
- Journal rows, corrections, FIFO positions and existing valuation/performance
  results remain unchanged by import, analysis and deletion.
- No snapshot UI or result presents gains or historical account performance.
  Documentation and navigation continue to label unbuilt features as proposals.

## Practical limits

The five-instrument cap deliberately excludes larger portfolios in this first
slice. A supported template requires users to reshape broker exports; automatic
mapping is not promised. Historical ticker changes and unsupported listings may
prevent import. These are explicit usability limits to evaluate before expanding
formats, instrument counts or analysis, not silent truncation rules.
