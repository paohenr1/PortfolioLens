# Private watchlists

The current watchlist version (0.28) adds [daily market information and saved
preferences](watchlist-market.md). The original bookmark workflow below remains
available; its dated verification counts record the 0.13 milestone.

Version 0.13 adds private instrument bookmarks to the existing Django application.
After signing in, choose **My watchlists**, then **Create watchlist**. On an
instrument's research details page, choose **Add to watchlist**, select one of
your lists, and submit **Add instrument**. You can also enter the stable Intrinio
instrument ID through **Add instrument** on a watchlist.

Each saved row links to instrument details, price history, and company financials.
**Remove** opens a confirmation page; **Keep instrument** cancels, and the
CSRF-protected **Remove instrument** submission removes that bookmark. You may
add it again later. No watchlist rename, deletion, sharing, or transfer workflow
is included in this part.

## Identity, provenance, and cost

A new bookmark makes exactly one instrument-reference request through the
existing Intrinio adapter and shared process-local request budget. Lists and
forms make no provider calls. Removing a bookmark also makes none. Re-adding an
already saved ID returns the existing row without a request or reference update.
Two concurrent additions can each spend one reference request, but save one row.

Identity uses the stable provider ID, independently of ticker, so separate
listings and share classes remain distinguishable. The reference snapshot stores
ticker, name, exchange MIC, trading currency, listing status, and an aware
retrieval timestamp. Missing fields stay unavailable. These fields describe the
reference at addition time and do not establish current listing status, prices,
feed freshness, or tradability. No full provider payload, authenticated URL,
price, financial statement, valuation, or automatic refresh is stored here.

Unlike a USD portfolio journal, a watchlist can bookmark a reference with another
or unknown currency/venue. This does not establish price/fundamental entitlement
or permit cross-currency totals. Research pages retain their own explicit data
requests and unavailable states. Re-adding a removed instrument gets a new
reference snapshot. There is no quote polling, alert service, new dependency,
hosted database, or additional subscription purchase.

## Privacy and bounded writes

- PostgreSQL is required, as for private portfolios. SQLite returns an explicit
  private 503 and cannot silently pretend watchlists are configured.
- Owner identity comes from the authenticated user. All list/item lookups and
  mutation services filter by that owner; UUIDs alone are not authorization.
- Foreign and missing lists/items use the same generic private 404. The
  selection form queries only the current owner's lists and rejects forged
  selections. Private pages, CSRF failures, method errors and route errors are
  marked no-store. Names and reference values are HTML escaped.
- Names are at most 100 characters, stripped, nonblank, and control-free. A
  database constraint enforces unique `LOWER(TRIM(name))` per owner.
- Up to 50 lists per account and 100 instruments per list are enforced by
  application services. Creation locks the owner row; additions/removals lock
  the watchlist row. Limits remain safe for concurrent application requests.
  Direct administrative writes can bypass these application allowances.
- Before reference I/O, additions check ownership, valid ID, duplicate status,
  and capacity. After I/O, the locked write repeats ownership and capacity
  checks. Database uniqueness enforces one ID per list. Provider I/O never
  holds the database lock.
- A mismatched returned ID, invalid reference fields or naive timestamp cannot
  become a bookmark. Safe provider failures preserve existing entries and the
  submitted form; rate failures return 429 and Retry-After. Unexpected
  exceptions log a fixed operation message without exception details.
- Only POST can change records; removal GET is a confirmation. Removing a row
  from a different list or owner is denied. Account deletion cannot silently
  remove owned lists.

Apply `watchlists/0001_initial` using the existing development database settings:

```sh
export UV_CACHE_DIR=/workspace/.cache/uv
uv run --frozen --env-file .local/database.env python manage.py migrate --noinput
```

The migration adds watchlist tables and constraints; it does not change journal
entries, accounting definitions or the immutable-ledger trigger.

## Verification and limits

The module adds 36 tests: two form tests, one storage guard, and 33 PostgreSQL
tests. They cover owner isolation and forged IDs, constraints, empty/unknown and
non-USD references, escaping, pagination, duplicate/re-add behavior, caps, safe
provider failures, actual adapter/shared-budget use, CSRF and method guards, and
four real database races for duplicate names/IDs and list/item allowances.

Full PostgreSQL: **518 passed, no skips**. Full SQLite: **302 passed, 216 skipped**;
those skips explicitly exclude PostgreSQL persistence/concurrency behavior.
Ruff lint/format, Django checks, migration drift and static collection pass.

The optional browser runner uses its own disposable PostgreSQL database and an
explicit synthetic HTTPX reference transport. Desktop and mobile checks cover
two users, details-page selection, duplicates, keyboard controls, removal
confirmation/cancellation, CSRF, provider failure, forged owner and sign-out.
It removes its child server/database and adds no development records. Screenshots
are `/tmp/stock-watchlists-*.png`; normal startup never enables this fixture mode.
Existing performance and valuation/allocation browser regressions also pass.

```sh
uv run --frozen --env-file .local/database-test.env python manage.py test --noinput
python3 tests/browser_watchlists.py
```

This part adds no live API acceptance check. The adapter's earlier live reference
checks remain separate evidence. Saved references are not current quotes.
Subscription storage/display/redistribution rights, production deployment,
distributed quotas, account recovery, and public sharing remain unverified or
future work. Explicit [corrections](corrections.md) are implemented. Bounded [daily session returns](daily-returns.md) are implemented. Observed [volatility and drawdown](risk.md) are implemented. Daily market information and saved preferences are now implemented. Next: broader live-data and complete user-journey acceptance testing.
