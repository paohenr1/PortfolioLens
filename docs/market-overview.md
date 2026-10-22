# Market overview

The homepage shows three fixed U.S. index cards: S&P 500, Dow Jones Industrial
Average and Nasdaq Composite. Opening or refreshing the initial page makes no
market-provider requests. Choose a chart range and explicitly select **Load market
overview**. The overview uses provider-reported historical index `level` observations,
not ETF prices, intraday quotes or a constructed total-return series.

## Dates and calculations

Requests exclude the current UTC date. Each card shows its actual latest supplied
observation date, which may be older than the requested cutoff. Retrieval timestamps
are separate and appear with the observation tables; they do not establish freshness.
The site does not call a dataset current simply because the credential is configured.

The point change is the latest level minus the immediately preceding supplied
observation. Percentage change is that difference divided by the preceding level,
multiplied by 100. The comparison date appears on the card. If the preceding supplied
observation has no value, the change stays unavailable. The comparison is not relabeled
as a one-session change when coverage or date spacing cannot establish that claim.
Levels, changes and percentages display two decimals with half-up rounding; calculations
use the supplied Decimal values before display rounding.

Chart windows are 1D, 1W (7 calendar days), 1M (30 days) and 1Y (365 days). The 1D
chart uses the latest supplied observation and its predecessor, including over weekends.
Other windows show supplied observations inside their selected calendar window. The
comparison on the card remains between the latest two supplied observations regardless
of chart window. Missing values break chart paths. Absent dates are not reconstructed;
there is no forward fill, earlier-date substitution for an explicitly missing value,
or adjusted-price fallback. Tables retain the supplied dates and unavailable values.

The request includes ten preceding calendar days for comparison/baseline discovery.
A response without usable observations in the selected window stays unavailable.
For 1D, no supplied values in that ten-day lookback also leaves the card unavailable.

## Provider contract and bounded requests

The backend calls the fixed Intrinio endpoint:

`GET /indices/stock_market/{symbol}/historical_data/level`

The allowlisted identities are `$SPX` / `ind_NX6GzO`, `$DJI` / `ind_2zvNzA`, and
`$COMPQ` / `ind_gPrpGL`. Both response ID and symbol must match. Each request allows
one page of at most 400 observations; an outstanding pagination cursor leaves that
response unavailable. Duplicate/out-of-range dates, invalid identity, malformed types,
and nonpositive/nonfinite/out-of-bounds index levels are rejected.

Official contract references:
- [Index API](https://github.com/intrinio/python-sdk/blob/master/docs/IndexApi.md#get_stock_market_index_historical_data)
- [Index historical response](https://github.com/intrinio/python-sdk/blob/master/docs/ApiResponseStockMarketIndexHistoricalData.md)
- [Index metadata](https://github.com/intrinio/python-sdk/blob/master/docs/StockMarketIndexSummary.md)

The index portion makes at most three provider requests, sharing the existing per-client/global
market budgets. Invalid forms, missing credentials, GET and HEAD do not spend provider
requests. CSRF protection applies to the POST load. Rate exhaustion stops remaining
requests and preserves Retry-After; individual unavailable datasets do not erase other
valid cards. PostgreSQL budget failures fail closed before provider I/O. No automatic
polling, retries or successful-result caching is introduced. Result pages use no-store.

## Public watchbar sources

The same explicit overview load also requests three public sources (six total upstream
requests including indices), using the shared market admission budget. Each source is
requested once, with no automatic retries, polling or caching. Hiding watchbar items
is a browser-local visibility preference and does not trigger requests.

- **U.S. 2-year and 10-year yields:** the current calendar year's official
  [Treasury daily curve XML](https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value=2026).
  Values retain percent units. Change is the difference between the latest two supplied
  observations multiplied by 100, displayed in basis points. Zero yields are valid;
  missing latest values are not replaced by earlier values. Early in January the
  current-year feed may have no observations or no change baseline; no previous-year
  substitution is performed.
- **USD/CAD:** Bank of Canada daily average reference rate, in Canadian dollars
  per U.S. dollar, from `FXUSDCAD`.
- **EUR/USD:** a derived daily reference cross-rate: `FXEURCAD / FXUSDCAD`, using
  both observations from exactly the same date. This is not an independently published
  Bank of Canada EUR/USD quote or an intraday tradable rate. Percentage changes compare
  unrounded cross-rates on the latest two supplied dates. Either missing component
  leaves the cross-rate unavailable, without mixing dates. The source is
  [Bank of Canada Valet](https://www.bankofcanada.ca/valet/observations/FXUSDCAD,FXEURCAD/json?recent=5).
- **BTC/USD:** [Coinbase Exchange BTC-USD 24-hour product statistics](https://api.exchange.coinbase.com/products/BTC-USD/stats).
  Price is the statistics response's `last`; percentage change is `(last / open - 1) × 100`.
  The response does not provide a quote timestamp. Retrieval time is shown separately
  and does not establish freshness. This is a single venue's rolling-window statistic,
  not a consolidated crypto quote or a daily-close comparison.

Source labels, observation/comparison dates and retrieval times appear under **Dates,
values and sources**. Different sources have different bases and are not presented as
one synchronized live feed. Yield changes use one decimal in basis points; FX values
use four decimals; BTC price and percentage changes use two. Display rounding is half-up.

Public-source requests use fixed HTTPS destinations, normal proxy/CA trust, no credentials,
no redirects and a 2 MiB decoded response limit. JSON rejects duplicate fields and
nonfinite constants; Treasury XML rejects DTD/entity declarations and non-UTF-8 input.
Malformed identities, dates and numeric values fail closed. Failures remain local to
the affected widgets; rate exhaustion stops remaining source requests and preserves
Retry-After. Missing Intrinio credentials do not prevent public-source widgets loading.

Cloud execution needs outbound access to `home.treasury.gov`, `www.bankofcanada.ca`
and `api.exchange.coinbase.com`; these feeds require no added API-key bindings.
Public reachability alone does not establish redistribution rights for another audience.

## Remaining feeds

Heatmap, news and calendar still show explicit unavailable states. The current Intrinio
account denied the S&P constituent endpoint during bounded verification; no placeholder
constituents, sector weights or market caps are presented as real market coverage.
Source access must be established before those sections are populated.

The development design preview remains separately available at `/design/markets/`
only with debug enabled outside production. It contains clearly labeled fictional
fixtures. Its controls are not live-provider controls.
