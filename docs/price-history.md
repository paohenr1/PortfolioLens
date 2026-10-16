# Historical daily prices and charts

Historical price pages show raw or provider-adjusted daily closes. The same load
supports [volume](volume.md) and, with sufficient complete observations, [stock
volatility and drawdown](stock-risk.md). Realtime prices are unsupported.

## User workflow

Search for an instrument, select its stable provider ID, and choose **View price
history** on the reference page. Choose start/end dates and adjusted or raw
close plus an independent volume basis, then **Load prices**. The initial form
suggests 90 days ending on the preceding UTC day but
does not request prices until submission. Changing a field alone makes no request.

The backend requests `GET /securities/{id}/prices` with inclusive `start_date`
and `end_date`, `frequency=daily`, and `page_size=100`. Returned identity must
match the selected ID, with consistent currency and exchange venue on every
page. Currency comes from the returned security metadata;
unavailable currency is labeled, never assumed to be USD. Search coverage is
provider-dependent and is not an entitlement promise for every listed instrument.

## Definitions and presentation

| Field or behavior | Definition |
| --- | --- |
| Raw close | Intrinio's `close`, unadjusted price at the end of the daily period |
| Adjusted close | Intrinio's `adj_close`, documented as adjusted for splits and dividends |
| Completed daily period | `frequency=daily` and `intraperiod=false`; true or unknown period status is excluded from the chart |
| Latest plotted close | Most recent returned completed observation with a nonmissing value for the chosen basis |
| Latest returned observation | Most recent supplied observation date, including incomplete/unconfirmed records; not a quote timestamp |
| Retrieval time | UTC time when the bounded retrieval completed, separate from the observed dates |
| Partial pagination | Another cursor remained after four pages; the chart explicitly warns that retrieval stopped |

Prices remain `Decimal` from JSON parsing through exact value display. SVG
coordinates are presentation geometry, rounded to three decimal places; they
are never inputs to valuations or accounting. Axis labels use four significant
digits, and the vertical range is fitted to displayed observations. Date
positions use actual calendar spacing rather than equal spacing between rows.
Constant and zero series are supported. The table shows both supplied bases
and period status, including values excluded from the chart.

Missing selected closes break chart segments. A missing adjusted close does
not fall back to raw close. Values are never interpolated, filled with zero,
or carried forward. Entirely absent dates are not synthesized: lines connect
the supplied observations, and no exchange trading calendar is assumed.
Consequently the application cannot diagnose missing trading sessions or prove
full market coverage just because pagination has ended. No freshness guarantee
or real-time availability is implied by these daily data.

This describes the supplied-price chart. The separate stock risk panel validates
a regular U.S. equity session calendar and requires every completed selected
close. It withholds statistics on gaps and partial history, without another
request; see [risk definitions and limits](stock-risk.md).

The provider's adjustment fields are displayed as supplied. The application does not
independently reconstruct the adjustment method or claim a portfolio total-return
series. Ledger valuation and dividend accounting use explicit share/cash-flow policies
documented in [valuation](valuation.md).

## Cost and failure bounds

- Date ranges start on/after 1900-01-01, end no later than the current UTC date,
  and contain at most 366 days including both endpoints. A single date is valid.
- One submission makes at most four requests, with at most 100 rows per page
  and 366 unique observation dates. Each page uses the existing shared
  budget of 10/client and 30 total requests per minute. Search and detail calls
  share the same budget. Production admission is shared through PostgreSQL.
- Response size is at most 256 KiB per page. Existing verified TLS, no redirects,
  3-second connect/5-second I/O timeouts, and per-page streaming checks apply.
  Four page limits do not create a hard wall-clock deadline for the whole action.
- Duplicate dates, cursor cycles, missing pagination metadata, inconsistent
  identity/currency, wrong frequency, malformed prices, and out-of-range dates
  fail validation. Prices must be finite, nonnegative JSON numbers with bounded
  representation (at most 1e12, 28 digits, exponent from -18 through 12).
- A request/validation failure on any page cancels the chart and returns the
  existing safe error state. Only stopping at the explicit page cap produces
  a labeled partial chart. Authentication/entitlement errors are HTTP 503,
  not empty history; rate limits are HTTP 429 with bounded `Retry-After`.
- No retries, background requests, prefetching, persistent market-data cache,
  or fixture fallback is implemented. Result/error responses
  use `Cache-Control: no-store`; licensing must be checked before caching or
  public display.

## Modules and chart choice

`market_data/contracts.py` defines immutable daily observations and results;
`prices.py` validates dates/prices; `intrinio.py` handles bounded paging.
`research/services.py` reserves quota per page; forms/views orchestrate the
workflow. `research/charts.py` prepares chart geometry and values independently
of Django, the network, and persistence.

The first line chart uses server-rendered SVG and a small local JavaScript
point inspector rather than introducing Plotly. Date/basis controls and the
observations table work without JavaScript. Pointer inspection reads the
already-rendered points and makes no requests. The scrollable chart/table
contain their own overflow on mobile; the table offers keyboard-accessible
exact values. No third-party chart package, external assets, or Node build is needed.

## Limitations

Provider-adjusted closes do not establish a particular total-return methodology. Partial
or missing observations remain labeled; no interpolation or prior-close substitution is
performed. Live coverage and display rights depend on the configured subscription.

See [setup and checks](setup.md#automated-checks) and the [methodology
index](methodology.md) for related calculations.
