# Market overview

The homepage shows three fixed U.S. index cards: S&P 500, Dow Jones Industrial
Average and Nasdaq Composite. Opening or refreshing the initial page makes no
market-provider requests. Choose a chart range and explicitly select **Load daily
levels**. The overview uses provider-reported historical index `level` observations,
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

A load makes at most three provider requests, sharing the existing per-client/global
market budgets. Invalid forms, missing credentials, GET and HEAD do not spend provider
requests. CSRF protection applies to the POST load. Rate exhaustion stops remaining
requests and preserves Retry-After; individual unavailable datasets do not erase other
valid cards. PostgreSQL budget failures fail closed before provider I/O. No automatic
polling, retries or successful-result caching is introduced. Result pages use no-store.

## Remaining feeds

Watchbar preferences can be changed in this browser, but Treasury yields, BTC/USD and
FX values remain **Not connected**. Heatmap, news and calendar show explicit unavailable
states. The normal application never loads the fictional design-preview datasets.
Feed coverage and access must be established before these widgets are populated.

The development design preview remains separately available at `/design/markets/`
only with debug enabled outside production. It contains clearly labeled fictional
fixtures. Its controls are not live-provider controls.
