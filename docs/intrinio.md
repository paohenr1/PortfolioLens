# Intrinio market-data integration

Implemented on October 10, 2026. Authenticated search and instrument-reference
acceptance passed that day. Bounded daily-price access and charts also passed;
AAPL annual income/balance/cash-flow statement access and browser pages also
passed. See [price-history definitions](price-history.md) and
[fundamentals definitions](fundamentals.md).

## Supported path

1. Open stock search and enter a ticker or company name (1–100 characters).
2. Submit explicitly. The backend requests `GET /securities/search` with
   `query` and `page_size=20`; there are no requests while typing.
3. Compare names, tickers, exchange MICs, and currency where supplied.
4. Select a result by its opaque Intrinio ID. The backend requests
   `GET /securities/{id}` and verifies that the returned ID matches.
5. Review reference fields, listing status, provider ID, and the provider's
   latest recorded historical-price date where available.

Search is not automatically restricted to U.S. listings: provider coverage
determines the returned instruments. Listings with identical tickers remain
separate. Missing fields say Unavailable rather than zero or inferred USD.
The reference page shows no quote or valuation. Its **View price history** link
opens the separate daily-close chart. **View company financials** opens explicit
statement/year/period selection and standardized observations.

The UTC retrieval time is when the reference response was received. A
`last_stock_price` date remains a date; it is not a quote timestamp or proof of
fresh market data. Old dates are displayed as provider reference metadata and
are not described as live prices.

## Verified contracts and remaining account questions

Official GitHub sources inspected:

- [Search and security lookup](https://github.com/intrinio/python-sdk/blob/master/docs/SecurityApi.md)
- [Search response](https://github.com/intrinio/python-sdk/blob/master/docs/ApiResponseSecuritiesSearch.md)
- [Search summary fields](https://github.com/intrinio/python-sdk/blob/master/docs/SecuritySummary.md)
- [Full security fields](https://github.com/intrinio/python-sdk/blob/master/docs/Security.md)
- [Daily prices and adjustment fields](https://github.com/intrinio/python-sdk/blob/master/docs/StockPriceSummary.md)
- [Historical-price response and pagination](https://github.com/intrinio/python-sdk/blob/master/docs/ApiResponseSecurityStockPrices.md)
- [Company fundamental lookup](https://github.com/intrinio/python-sdk/blob/master/docs/CompanyApi.md#lookup_company_fundamental)
- [Standardized financial endpoint](https://github.com/intrinio/python-sdk/blob/master/docs/FundamentalsApi.md#get_fundamental_standardized_financials)
- [Statement metadata](https://github.com/intrinio/python-sdk/blob/master/docs/Fundamental.md)
- [Financial response](https://github.com/intrinio/python-sdk/blob/master/docs/ApiResponseStandardizedFinancials.md)
- [Standardized values and units](https://github.com/intrinio/python-sdk/blob/master/docs/DataTagSummary.md)
- [API host and query-key authentication](https://github.com/intrinio/python-sdk/blob/master/intrinio_sdk/configuration.py)

The user reported US Fundamentals and Stock Prices (Individual, yearly),
U.S. historical prices, U.S. fundamentals, EOD index levels, and delayed/streaming
feeds. No additional subscription is proposed. These names do not establish
endpoint-level access, coverage, current limits, or public display/caching rights.
Confirm those separately before exposing the application publicly.

On October 10, 2026, the published cloud configuration reported a saved vault
binding for `INTRINIO_API_KEY` and allowed `api-v2.intrinio.com`. The management
command below completed authenticated AAPL search and lookup of a returned
instrument ID. A separate browser check completed search and selection against
the running application, with the detail page checked at desktop and mobile
widths. These checks used four backend reference requests total, no retries,
and no fixture fallback. No key values or raw responses were recorded.

## Credential and request safety

- Requests originate only from the Python backend to the fixed HTTPS API host.
- HTTPX retains TLS verification, system/environment trust configuration, and
  the platform's existing proxy route. Credentials are not extracted from it.
- The documented key is a query parameter; frontend requests never include it.
  Logging filters redact raw/URL-encoded configured keys and `api_key` URL
  parameters, including exception traces. New logging handlers must retain
  the same filter; do not enable an unfiltered diagnostic sink.
- Provider error bodies and authenticated request URLs are not returned to users.
  Credential echoes in otherwise valid JSON records are rejected.
- Redirects are rejected; they cannot send credentials to another host.
- Requests have a 3-second connect and 5-second per-I/O timeout, plus a
  10-second streaming budget checked between chunks. This is not a hard
  whole-operation deadline: a current I/O wait can last until its timeout.
- Decoded response size is limited to 256 KiB. Duplicate JSON fields,
  nonfinite numbers, malformed types, duplicate security IDs, excess results,
  and inconsistent detail identities are rejected.
- No automatic retries, prefetching, or success-data caching is implemented.
  Licensing must permit retention before a market-data cache is introduced.
- Successful/error result pages use `Cache-Control: no-store`.

## Cost guards

Search, detail, each price-page, and each statement-stage request share a
fixed-window budget: 10 admitted upstream
requests per client address and 30 total per minute. Invalid input,
empty forms, missing credentials, POST, and HEAD do not cause provider calls.
Forwarded client-address headers are not trusted without a verified proxy.

Development memory counters use a monotonic clock and lock, retain at most 30
client hashes per window and reset on process restart. Production now requires
shared PostgreSQL counters, using the database clock and durable row locking;
worker restarts and separate processes share the same allowance. Storage failure
returns a fixed 503 before provider I/O, without memory fallback. See
[release safeguards](release-safeguards.md). Fixed windows still allow boundary
bursts. This is not a replacement for actual subscription limits or an account-wide
quota across deployments using different databases. Clients behind an unverified
proxy share its address allowance.

Provider rate limits return HTTP 429 with a bounded `Retry-After` (1–3600
seconds). Authentication/entitlement/transport/invalid-data failures return safe
HTTP 503 pages. A missing reference record returns HTTP 404. A search endpoint's
404 is treated as unavailable rather than as proof of no matching ticker.

## Live acceptance after secure configuration

In environment settings, supply `INTRINIO_API_KEY` securely and permit
`api-v2.intrinio.com`. The environment configuration declares this credential for that HTTPS
destination, preserving existing bindings and allowed destinations. Saving a
draft does not apply its values, update a running process, or publish it.

After the configuration is applied and the process restarted, run from the
repository root:

```sh
uv run --frozen python manage.py verify_intrinio --query AAPL
```

For a local ignored `.env`, insert `--env-file .env` after `--frozen`. The command
uses at most two requests: search, then one returned ID lookup. A missing key,
network/provider error, or no selectable result yields a nonzero exit. It prints
no credentials or raw responses. Success proves those two endpoint operations
only; price/fundamental datasets and the browser workflow require their own
live checks. The separate bounded price check is:

```sh
uv run --frozen python manage.py verify_prices --query AAPL
```

Its default range is the last 30 calendar days, adjusted close. Optional
`--start-date YYYY-MM-DD --end-date YYYY-MM-DD --basis raw` changes the inputs.
It uses one search plus at most four price requests, and fails for denied access,
no usable completed closes, or unfinished pagination. Do not run either live
command on every startup or health check. Account quotas, coverage, pricing,
and display/caching rights remain separate questions.

The separate statement check is:

```sh
uv run --frozen python manage.py verify_fundamentals --query AAPL --fiscal-year 2025 --fiscal-period FY
```

Its default statement is `income_statement`; `--statement-code
balance_sheet_statement` or `cash_flow_statement` selects the other statements.
It makes at most four requests (search plus the three-stage statement workflow),
and requires usable values with no indicated continuation. It does not prove
forecasts, point-in-time history, or other periods/instruments. It is not a
startup or health check. Missing financial tags never become zero or substitute
metrics. Statement units come from data tags, independently of listing currency.

## Tests and limitations

The 518 Django tests include HTTPX MockTransport integration and failure cases.
The optional browser runner performs desktop/mobile search, selection, and price charts using
explicitly synthetic fixtures; see [setup](setup.md) and the
[fixture notes](../tests/fixtures/README.md). No fixture is a production fallback.

Live search/reference access and browser selection are validated for the tested
query. Daily AAPL close access and a one-year raw/adjusted browser chart also
passed (251 completed observations). AAPL 2025 FY standardized income, balance-sheet,
and cash-flow pages passed (22, 30, and 22 supplied rows respectively), including
the restated balance-sheet classification. Other instruments/periods, account quotas, wider
coverage, and licensing have not been validated.
There is no application data cache, persistence for market data, websocket
client or deployment yet. Accounts and private portfolio metadata are implemented
separately; neither workflow requests market data. The [USD journal](ledger.md)
stores immutable current reference snapshots for trades, not price-history or
statement caches. A new trade, dividend, or split uses one instrument lookup; cash entries, reads,
and exact submission retries use none. [FIFO positions and realized gains](fifo.md)
use only journal snapshots and make no provider requests.

Recorded dividend/split entries verify current instrument references only;
no corporate-action endpoint or action completeness is verified. Ratios, dates
and net receipts are supplied by the user; see [action rules](corporate-actions.md).


## Dated company market capitalization (0.27)

[Company market capitalization](market-capitalization.md) uses a separate company
historical-data request and verified `marketcap` USD tag metadata. It reserves up
to three requests under the same budget. This feed/date works with the existing
vault-bound subscription in live AAPL acceptance. Underlying price/share-count
dates and calculation methodology remain unavailable/unverified; the application
never guesses them or uses weighted-average earnings shares to reconstruct cap.


## Watchlist daily market information (0.28)

[Watchlist daily loads](watchlist-market.md) reuse one exact-date, single-page
price request for each of at most five selected owned bookmarks. Each request
spends the shared budget; a limit stops further loads. No implicit reference
refresh or cached quote is introduced. Prices/volumes are dated daily observations,
not live quotes. Preference saves and unsubmitted forms make no provider calls.
