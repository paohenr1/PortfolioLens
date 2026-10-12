# Dated company market capitalization

From instrument details or company financials, choose **View company market
capitalization**, select an exact **Market capitalization date**, then **Load
market capitalization**. The blank form requests no market data. Dates must be
calendar dates from 1900 through today in UTC; suggested dates do not establish
available data. The public research response is not cached (`Cache-Control: no-store`).

## Why display the provider's value?

The live AAPL fiscal-2025 balance-sheet feed did not contain an outstanding-share
count. Weighted-average basic/diluted income-statement shares describe an earnings
period and must not be treated as outstanding shares at a valuation date.
Your existing Intrinio plan supplies the separate `marketcap` company historical
data tag, so this module displays that provider-reported value directly. It does
not multiply a listing price by unverified company shares or add a paid dataset.

The metric covers the provider's **company** scope, not just the selected listing
or share class. The selected instrument must have a verified company ID, and the
historical response must identify that same company. A separate tag metadata
request must confirm `marketcap`, unit `usd`, statement `calculations` and type
`valuation`. Metric USD is independent of the listing's trading currency; no FX
conversion is performed. A non-USD listing can therefore link to a USD company
observation without implying a local-currency value.

## Dates and missing information

The page shows the selected provider observation date, UTC retrieval timestamp,
company/instrument identities, metric currency and source tag. This endpoint
does **not** supply the underlying price timestamp, shares-outstanding count/date,
observation completion flag, share-class coverage or split methodology. Those
dates/counts remain explicitly unavailable, and the methodology remains unverified.
The valuation date cannot establish the underlying input dates.

These are currently retrieved historical observations, not historical-as-known
values or live quotes. A current-day observation is not asserted to be a completed
closing value. The application does not reconstruct the provider's formula,
infer missing dates/counts, forward-fill prior observations or promise immutable
historical versions. The full input-date requirement remains limited by the feed.

The supplied nonnegative value retains its exact decimal precision and displays
with digit grouping, without application rounding. A supplied zero remains zero.
No date observation, a dated null value and incomplete pagination have distinct
messages and display **Unavailable**. A single-date request with a cursor is not
followed, and its numeric value is withheld. Duplicate or wrong-date observations,
identity/unit mismatches and malformed or unsupported values fail validation.

## Request and validation boundaries

Each load uses at most three backend requests:

1. `/securities/{stable_id}` verifies the selected instrument/company association.
2. `/data_tags/marketcap` verifies the metric identity, USD unit and scope.
3. `/companies/{company_id}/historical_data/marketcap` requests exactly the selected
   date, daily frequency, ascending order and at most two rows on one page.

Only one observation is accepted for the exact date. Fixed endpoint paths use
validated provider IDs; no browser request contains the API credential. Every
request spends the shared 10-per-client/30-total per-process minute budget.
Missing credentials, authentication/entitlement failures, rate limits, missing
feeds, invalid responses and network errors retain the existing safe error
boundary. There is no retry, market-data storage or caching. A shared quota store
is still needed before a public multi-worker deployment.

JSON values must be finite nonnegative numbers, at most `1e24`, with at most 40
coefficient digits and exponents from -18 through 24. Strings, booleans, negative
values and nonfinite numbers are rejected. These bounds prevent large fixed-point
HTML expansion. The inherited HTTPS proxy, CA trust and TLS verification remain
enabled; provider bodies and authenticated URLs are never displayed.

The response shape follows the official Intrinio Python SDK documentation for
[company historical data](https://github.com/intrinio/python-sdk/blob/master/docs/ApiResponseCompanyHistoricalData.md),
[historical observations](https://github.com/intrinio/python-sdk/blob/master/docs/HistoricalData.md)
and [data tags](https://github.com/intrinio/python-sdk/blob/master/docs/DataTag.md).
The company historical response omits tag units, which is why the separate
metadata check is required.

## Verification and remaining scope

Version 0.27 adds 30 automated tests covering exact values, zero/null/missing
observations, identity/unit/date checks, cursor bounds, malformed numbers,
hostile decimal contexts, bounded requests, quota interruption, safe errors,
escaping and blank/invalid forms. Focused regression: 105 passed. Full PostgreSQL:
914 passed with no skips. SQLite: 659 passed, 255 PostgreSQL-only skipped.

The optional `python3 tests/browser_capitalization.py` runner passes seven
explicitly synthetic desktop/mobile scenarios: supplied value, zero, missing,
null, partial, wrong unit and wrong date. It checks date controls, navigation,
source/unknown-input labels, horizontal overflow, local-only browser requests,
safe errors and rate limiting. Test-only servers clean up; public research forms
create no account, portfolio or temporary browser database. Synthetic screenshots
are written only to `/tmp`, and fixtures are never a production fallback.

Live normal-application AAPL/XNAS acceptance passed on October 11, 2026 for the
October 9 observation, with a positive supplied USD company value, source/date
labels, desktop/mobile controls and `no-store`. Browser navigation used five
backend calls: search, instrument details and the three-stage cap load. Earlier
bounded diagnostic calls established the feed and metadata shapes. No live value,
raw response, screenshot or credential was retained in artifacts.

This acceptance establishes this feed/date/instrument only. Wider coverage,
account quotas, display/redistribution rights and provider methodology remain
unverified. Underlying price/share-count provenance requires a suitable feed;
enterprise value, valuation recommendations and production deployment remain
outside this module. Next: watchlist market information and saved preferences.
