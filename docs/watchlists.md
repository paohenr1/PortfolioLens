# Private watchlists

After signing in, choose **My watchlists**, then **Create watchlist**. On an
instrument’s research details page, choose **Add to watchlist**, select a list, and
confirm. Lists support [daily market information and saved
preferences](watchlist-market.md).

## Identity, provenance, and cost

A new bookmark makes exactly one instrument-reference request through the existing
Intrinio adapter and shared request budget. Lists and forms make no provider calls.
Removing a bookmark also makes none. Re-adding an already saved ID returns the existing
row without a request or reference update. Two concurrent additions can each spend one
reference request, but save one row.

Identity uses the stable provider ID, independently of ticker, so separate
listings and share classes remain distinguishable. The reference snapshot stores
ticker, name, exchange MIC, trading currency, listing status, and an aware
retrieval timestamp. Missing fields stay unavailable. These fields describe the
reference at addition time and do not establish current listing status, prices,
feed freshness, or tradability. No full provider payload, authenticated URL,
price, financial statement, valuation, or automatic refresh is stored here.

Unlike a USD portfolio journal, a watchlist can bookmark a reference with another or
unknown currency/venue. This does not establish price/fundamental entitlement or permit
cross-currency totals. Research pages retain their own explicit data requests and
unavailable states. Re-adding a removed instrument gets a new reference snapshot. There
is no quote polling or alert service.

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
uv run --frozen --env-file .local/database.env python manage.py migrate --noinput
```

The migration adds watchlist tables and constraints; it does not change journal
entries, accounting definitions or the immutable-ledger trigger.

## Limitations

Saved references are not live quotes. Public sharing and alerts are unsupported.
Provider storage/display rights must permit the intended use. Daily market information
and saved preferences are documented separately.

See [setup and checks](setup.md#automated-checks) and the [methodology
index](methodology.md) for related calculations.
