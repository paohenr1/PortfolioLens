# Watchlist market information and saved preferences

Private watchlists support on-demand daily price/volume observations and saved display
preferences. Loads use the Intrinio historical feed and shared request budget; there is
no polling or background refresh.

## Using the feature

Open **My watchlists**, choose a list, then **Edit saved preferences**. Save the
default raw/adjusted price basis, independent raw/provider-adjusted volume basis
and instrument order (date added or ticker A–Z). These settings belong to that
watchlist and its owner. Saving uses a CSRF-protected POST, makes no provider
request and returns to the list with the defaults displayed.

Choose **View daily market information**, select an exact **Daily observation
date** and one to five instruments, then **Load selected market information**.
The saved bases supply the initial form values. You can override them for one
load; this does not change saved preferences. The date and instrument selection
are deliberately not saved. Reopening the plain form does not reload data.

Watchlist details stay paginated at 25 bookmarks. Saved ticker ordering is case
insensitive, with missing tickers last and stable date/ID tie-breakers. The market
selector offers the list's bounded collection of at most 100 bookmarks, in that
same order. No selection is checked automatically. A selection must contain one
to five distinct owned item IDs; duplicate, foreign and over-limit selections
fail before provider requests. Dates must be calendar dates from 1900 through
today in UTC. The suggested date does not establish trading/data availability.

The result table scrolls horizontally on small screens and is keyboard focusable.
It shows the selected close, selected share volume, response currency/venue,
requested date, UTC retrieval timestamp and per-item source/availability. Saved
name/ticker labels remain the bookmark reference; current price-response currency
and venue are displayed separately and do not rewrite the bookmark.

## Observation definitions

Raw close uses `close`; adjusted close uses `adj_close`. Raw volume uses `volume`;
provider-adjusted volume uses `adj_volume`. Bases are independent. Missing fields
do not fall back to another basis, date or instrument. A supplied zero stays zero;
fractional volumes and decimal prices retain their exact precision, with digit
grouping and no application rounding. Price and volume availability are separate:
a missing price or currency need not remove valid volume.

Both values require a complete single-row response for the exact selected date
and stable instrument ID, an aware retrieval timestamp that does not predate the
observation, and `intraperiod` explicitly `false`. Empty, ambiguous, wrong-date,
partial or unconfirmed responses withhold both values. A price also requires
explicit response trading currency and exchange MIC. A non-USD listing retains
its own currency; no cross-currency or cross-instrument total is calculated.

Values are finite nonnegative decimals. Closes are at most `1e12`, with at most
28 coefficient digits and exponents from -18 through 12; volumes are at most
`1e18`, with at most 36 digits and exponents from -18 through 18. Unsupported
values remain unavailable. The adapter additionally rejects malformed JSON,
duplicate dates, credential echoes, unsupported response sizes and invalid fields.

These are **dated daily observations, not live quotes**. A date-only observation
is not an exact quote timestamp. Adjusted prices may incorporate provider split/
dividend adjustments; volume uses its own provider adjustment basis. No independent
adjustment verification, total-return claim, price-change percentage, currency
conversion or monetary turnover is inferred. Price/volume responses are not stored.

## Cost, failure handling and privacy

Each selected instrument uses one exact-date `/securities/{stable_id}/prices` request
through the existing backend adapter. A single page is requested, and any continuation
is labeled incomplete without following it. Each request reserves the existing
10-per-client/30-total minute budget. Plain list/forms, sorting, preference saves and
bookmark removal spend no market-data quota.

Provider failures show fixed safe messages for the affected row; successful rows
remain available. A request-limit failure stops remaining instruments, labels
them not requested, and returns 429 with `Retry-After`, preserving earlier valid
rows. Other per-item errors return a rendered results page with their explicit
unavailable states. There is no automatic retry. Unexpected failures log a fixed
operation message without exception details or authenticated URLs.

Owner filtering precedes provider I/O and preference validation. The market form
queries only that watchlist's instruments. After network I/O, the service rechecks
ownership, active account and item membership; removal or loss of authorization
during a load discards the result with a generic private 404. Provider I/O holds
no application database transaction/row lock. Preference updates lock the owned
watchlist and update only the three preference fields. All private responses,
including route/method/CSRF errors, are marked no-store and escape saved labels.

Migration `watchlists/0002_market_preferences` adds three fields and database
choice constraints. Existing lists receive raw price, raw volume and date-added
order defaults; IDs, owners, bookmarks and reference timestamps remain intact.
Earlier migrations and immutable ledger guards are unchanged. Apply it with the
existing development setup; no data reset or database replacement is required.

## Limitations

Preferences are per watchlist. Realtime quotes, alerts, sharing, cross-currency totals
and caching are unsupported. Saved references and exact-date observations are not
current quotes.

See [setup and checks](setup.md#automated-checks) and the [methodology
index](methodology.md) for related calculations.
