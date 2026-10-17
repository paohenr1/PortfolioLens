# USD transaction journal

Each portfolio has a private transaction history and entry form. Choose **View
transactions**, then **Record transaction**. The journal records supplied events; it
does not send orders or verify brokerage executions. Original entries cannot be edited
or deleted. [Replacement/void corrections](corrections.md) require a preview and
confirmation and preserve a permanent audit trail.

## Accounting rules

The reporting and entry currency must explicitly be USD. Each entry has a date
and a same-day order number. Replay sorts by date, then order, independently of
when an entry was submitted. Dates run from January 1, 1900 through the current
day in America/Toronto; future entries are rejected. UTC timestamps separately
record submission and reference retrieval. Same-day order is unique within the
portfolio/date and ranges from 1 through 999999.

| Entry | Required inputs | Cash change | Share change |
| --- | --- | --- | --- |
| Deposit | Positive USD amount | +amount | None |
| Withdrawal | Positive USD amount | −amount | None |
| Buy | Security ID, positive quantity and execution price, optional fees | −(rounded gross + fees) | +quantity |
| Sell | Security ID, positive quantity and execution price, optional fees | rounded gross − fees | −quantity |
| Fee | Positive USD amount | −amount | None |

Cash entries must leave trade inputs empty; standalone fees use the Fee type.
Trade fees are nonnegative USD. An unusual sell whose fees exceed its proceeds
is allowed only if previously recorded cash covers the difference.

All calculations use Decimal, never floating-point. Money and fees accept at
most two decimal places and 1 trillion USD per field. Share quantity and manual
execution price (USD/share) accept at most six decimal places and 1 billion per
field. A trade's quantity × price is rounded once to cents using ROUND_HALF_UP;
the rounded positive gross must not exceed 1 trillion USD. A rounded-zero trade
is rejected. These are input/storage bounds, not economic plausibility checks.
The replay uses an explicit high-precision decimal context and retains exact
fractional share quantities. Recorded cash may exceed an individual input cap
after multiple deposits.

Every historical prefix must have nonnegative cash and nonnegative shares for
each stable security ID. A backdated entry is checked against the entire journal,
so an earlier withdrawal or sale cannot invalidate an already-recorded trade.
Margin, short selling, unsettled-funds treatment, and borrowing are unsupported.
Deposits are contributions, not profit; the cash figure is not net asset value,
investment performance, or a verified brokerage balance.

An independent example: deposit 1,000; buy 10 shares at 25 with a 1 fee → cash 749; sell
4 at 30 with a 2 fee → 867; withdraw 100 → 767; record a 3 fee → 764. Six shares remain
in replay. This establishes cash/share reconciliation only; the [FIFO module](fifo.md)
derives remaining cost and realized sale gains.

## Identity and request cost

Use the Intrinio security ID from an instrument's reference page, not a ticker
alone. A new valid trade, dividend, or split performs one instrument lookup through the existing
adapter and shared request budget. It requires matching ID, USD denomination,
a ticker, and a supported U.S. listing MIC: XNAS, XNYS, ARCX, BATS, IEXG, XASE,
XNMS, XNCM, XNGS, EDGX, or EDGA. This explicit reference allowlist does not
establish historical instrument coverage, exchange completeness, entitlements,
or data-display rights.

The journal stores a current ID/ticker/MIC snapshot and its retrieval timestamp.
It is not reference data as of the entered transaction date. Quantities are
tracked by stable ID, so ticker renames do not split holdings. A changed venue
for the same ID is blocked pending reference reconciliation. Delisted securities
whose current lookup fails cannot currently be entered. Execution prices are
always supplied by the user; market prices are never substituted.

Deposits, withdrawals, standalone fees, history reads, invalid balance inputs, and exact
duplicate retries make no provider request. A provider failure records nothing and
presents a safe error. Concurrent new trade attempts can each consume a lookup before
one wins the database lock.

## Ownership and write safety

Sign-in is required, and all lookups filter by the signed-in owner. Foreign and
missing portfolio UUIDs return the same private 404. Forms require CSRF and
explicit USD; owner and reference metadata submitted by callers are ignored.
Private responses, including errors, carry no-store headers. PostgreSQL is
required; SQLite portfolio and ledger routes return an unavailable state.

A form carries a hidden UUID client key. The same key and normalized inputs
return the existing entry without a new lookup or insert. Reusing it for changed
inputs is rejected. The key is unique within a portfolio; separate fresh forms
may intentionally record similar entries and are still subject to date/order
uniqueness. This is duplicate-submit protection, not brokerage deduplication.

Before insertion, an atomic transaction locks the portfolio row and repeats
idempotency, capacity, ordering, and full-history replay checks. Concurrent
withdrawals/sales cannot spend the same available cash/shares twice through this
service. PostgreSQL constraints also enforce identity shape, USD, numeric
bounds, trade gross rounding, order uniqueness, and client-key uniqueness.
Each portfolio is limited to 1,000 stored originals/replacements; an exact retry
remains accepted at the limit. History paginates at 25 effective rows while cash
uses the complete effective journal. Corrections preserve originals and enforce
one effective event per date/order, with server-controlled immutable revisions. Larger journals need a separately designed projection strategy.

Model methods reject edits/deletions; a PostgreSQL trigger also rejects direct
UPDATE and DELETE. This is not a tamper-proof audit system: database owners or
administrators can disable triggers, truncate tables, or bypass application
validation with direct INSERT. Historical balance checks rely on the write
service. Production roles, backups/restoration, retention, lock/query timeouts,
monitoring, and recovery remain operational work.

## Limitations

Entries are manually supplied research records. Brokerage imports, short positions,
margin borrowing, FX and tax reporting are unsupported. Positions and returns depend on
a complete, correctly ordered history.

See [setup and checks](setup.md#automated-checks) and the [methodology
index](methodology.md) for related calculations.
