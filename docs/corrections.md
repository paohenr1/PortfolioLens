# Transaction corrections

Version 0.14 adds owner-only **Correct** and **Void** controls to current
transactions. **Correct** replaces a mistaken event; **Void** removes it from
the current interpretation without a replacement. Both retain the original
entry, a permanent reason, and a correction timestamp in **View correction
history**. This is an accounting restatement, not a reversing trade, cash
transfer, brokerage instruction or tax-reporting claim.

## Review and save

1. Open **View transactions** and choose **Correct** or **Void** on the entry.
2. Enter a reason. For a replacement, review the prefilled event and change its
   date/order, kind, amounts, quantities, fees or explicit split terms.
3. Choose **Preview correction**. Nothing is saved and no provider request runs.
   The preview shows the original, proposed event, whole-journal cash, open
   basis, realized sale gain, and resulting open positions.
4. Review the effect, check the confirmation, and choose **Save correction**.
   The correction and any replacement commit together; the original is unchanged.

All existing event rules still apply: USD, explicit date/order, no short shares
or negative cash at any prefix, FIFO fee/basis rounding, exact per-lot split
conversion, and manually recorded actions. Later events must remain valid.
Voiding a funding deposit used by a buy is rejected. Reducing a buy below shares
used in a later sell is rejected. A received net dividend can remain after a buy
is voided: the existing dividend policy records cash received and does not infer
ownership or entitlement on an earlier record date.

A replacement identical to the original is rejected. Each entry can be targeted
once. If its replacement also needs correction, select that current replacement;
the audit preserves the complete chain. Correcting several dependent events
atomically is outside this part. Correct individual events only when the resulting
full journal is valid; do not insert compensating financial events merely to
force a correction through.

## Financial interpretation

Positions, transaction cash, dated valuations, allocation weights, and
time-weighted returns now read the same effective journal: all stored events
except targets of correction decisions. A replacement is an ordinary financial
event at its explicit event date/order. The correction audit record contributes
no shares or cash and is not a deposit or withdrawal.

For example, deposit $1,000, buy ten shares at $25 with a $1 fee, then sell four
at $30 with a $2 fee. Cash is $867, remaining basis $150.60 and realized gain
$17.60. Correcting the buy price to $20 gives cash $917, remaining basis $120.60
and realized gain $37.60. The original buy remains in the audit.

Past event-date calculations are restated using corrections known now. A
correction recorded today to an older event can change previously displayed
valuations and returns. There is no reconstruction of what the application
knew at an earlier recording time, preserved report version, or point-in-time
backtest guarantee. Audit timestamps describe when the correction was recorded;
event dates describe when the corrected financial activity occurred.

The original date/order is allowed for a replacement. Immutable entries carry a
server-controlled revision per date/order slot, so retaining an old version does
not consume the effective slot. A voided slot can also be reused by a later normal
entry. The database guarantees one effective event at each date/order and a
replacement's matching audit link at transaction completion. The old immutable
entry trigger stays installed.

## Privacy, concurrency, and request cost

- All routes/services require the authenticated active portfolio owner. Foreign
  or missing portfolio/entry IDs return generic no-store 404s. SQLite explicitly
  returns storage unavailable. Forms, errors and audit pages are private/no-store.
- Modifications require CSRF-protected POST. The preview's signed JSON binds
  owner, portfolio, target, replacement/void mode, validated details, reason,
  submission key and effective-journal fingerprint. It expires after 15 minutes.
  Signing authenticates the payload; it does not encrypt it.
- Saving ignores unsigned changes to transaction fields. The user must preview
  new details. Missing confirmation preserves the valid preview without saving.
- Any new effective entry or correction after preview requires a new preview.
  The service checks before provider I/O and again under the same portfolio lock
  used for normal appends. A concurrent append cannot mix earlier quantities
  into a later correction. A change during I/O aborts without a ledger write,
  although that reference request was already spent.
- Exact committed retries return the same correction without another request.
  Changed details under the same submission key are rejected. Entry and
  correction keys cannot be cross-reused. HTTP previews still expire; the
  committed audit remains available after expiry.
- Voids and cash/fee replacements make no provider requests. A new buy/sell,
  dividend or split replacement uses one existing bounded reference request
  outside the database lock, verifying ID/USD/venue. Safe provider errors retain
  the original and form, with no replacement or audit row. Rate failures preserve
  Retry-After. No quote polling, cache, dependency or paid service is introduced.
- Reasons are stripped, nonblank, control-free and at most 500 characters. The
  audit HTML escapes them. Corrections are insert-only at both ORM and PostgreSQL
  levels, with foreign-portfolio/self/cycle link checks and replacement completeness.
- The 1,000-entry allowance counts all stored originals and replacements; voids
  do not reclaim audit storage. There is a separate 1,000-correction allowance.
  A void can still fit at the entry limit. Audit pagination is 20 decisions/page.

Effective entries and correction exclusions are read in one SQL statement so
transaction visibility cannot mix a new replacement with an old exclusion list.
PostgreSQL deferred guards serialize direct insertions with `NO KEY UPDATE`,
which is compatible with foreign-key `KEY SHARE` checks. A direct-write race
initially exposed a deadlock under a stronger lock; the corrected guard passes
the race test without disabling foreign-key or integrity checks.

## Setup and verification

Apply both new migrations, `ledger/0004_corrections` and
`ledger/0005_correction_guards`, with the existing PostgreSQL settings:

```sh
export UV_CACHE_DIR=/workspace/.cache/uv
uv run --frozen --env-file .local/database.env python manage.py migrate --noinput
uv run --frozen --env-file .local/database-test.env python manage.py test --noinput
python3 tests/browser_corrections.py
```

The upgrade test confirms existing values remain unchanged, revision defaults
are correct and immutability remains active. After corrections exist, use forward
migrations; downgrading to the old unversioned uniqueness constraint is not a
supported way to remove this feature.

The module adds 44 tests: three form tests, one storage guard and 40 PostgreSQL
tests. Five concurrency checks cover identical retries, competing corrections,
append races, a journal change during provider lookup and direct SQL order races.
Other cases cover independently calculated FIFO/cash results, dividends/splits,
historical cutoff and external-flow restatement, signed scope/expiry/tampering,
stale previews, idempotency, rollback, reference failure, caps, audit escaping,
pagination, immutable storage and upgrade preservation.

Full PostgreSQL: **518 passed, no skips**. Full SQLite: **302 passed, 216 skipped**;
SQLite does not establish PostgreSQL persistence/concurrency. Ruff lint/format,
Django checks, migration drift and static collection pass.

The desktop/mobile browser runner uses its own disposable PostgreSQL database
and explicit synthetic reference/price transport. It checks hand-calculated
preview/save/audit, exact retry, void/reused order, later appends, corrected
valuation/allocation/returns, stale preview, ownership, CSRF and keyboard controls.
Screenshots are `/tmp/stock-correction-*.png`. Its child/database are removed;
normal startup never enables test fixtures or creates development records.

No new live API acceptance call or deployment is part of this module. Multi-event
corrections, as-known historical reports, complex actions, FX, tax accounting,
distributed quotas and production operations remain future work. Bounded [daily session returns](daily-returns.md) are implemented. Observed [volatility and drawdown](risk.md) are implemented. Next: benchmark comparison with aligned sessions.
