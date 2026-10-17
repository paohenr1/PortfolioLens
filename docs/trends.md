# Annual financial statement trends

Choose **View annual financial statement trends** from instrument details or company
financials. Select one statement, the last fiscal year and two to four consecutive FY
periods, then **Load annual trends**. Defaults suggest income, the preceding calendar
year and three periods; they do not guarantee available filings. Opening the form makes
no provider call.

## Definitions and scope

| Statement | Metrics and standardized source tags | Meaning |
| --- | --- | --- |
| Income | Revenue `totalrevenue`; operating income `totaloperatingincome`; net income `netincome` | Supplied totals over each annual income period |
| Balance sheet | Assets `totalassets`; liabilities `totalliabilities`; equity `totalequity` | Supplied point-in-time balances at each period end |
| Cash flow | Operating `netcashfromoperatingactivities`; investing `netcashfrominvestingactivities`; financing `netcashfromfinancingactivities` | Supplied net cash flows over each annual period |

Every displayed observation must explicitly use provider unit `usd`. Listing
currency does not establish a statement unit. Unknown/mismatched units, missing
tags and null values have distinct unavailable explanations. Zero and negative
amounts remain real observations. Nothing is converted, scaled into millions,
reconstructed from other tags or substituted from another statement type.

This first trend view supports three defined USD metrics per statement. It does
not include EPS, per-share book values, share-count trends, quarter/TTM/forecast
series or inferred split adjustments. Per-share trends need separately compatible
share definitions. The individual statement page still displays its other
supplied observations.

Dollar change = current value − immediately preceding FY value, exactly.
Percentage change = dollar change / prior value × 100, only when prior is
positive. Retain exact Decimal amounts and rational arithmetic; round only the
final percentage half up to two decimals. For zero/negative bases, retain the
dollar change and explain the unavailable percentage. Do not use an absolute
denominator or clamp losses, negative changes or percentages below -100%.
Balance-sheet changes compare two endpoint balances; they are not flow sums,
asset returns or return on equity.

Synthetic hand-calculated examples, used only in tests:

| Metric | 2017 FY | 2018 FY | 2019 FY | Adjacent dollar changes | Adjacent percentages |
| --- | --- | --- | --- | --- | --- |
| Revenue | 100 | 200 | 300 | +100; +100 | 100.00%; 50.00% |
| Operating income | 10 | 20 | 30 | +10; +10 | 100.00%; 50.00% |
| Net income | -20 | 0 | 30 | +20; +30 | Unavailable; unavailable |
| Investing cash flow | -5 | -10 | -15 | -5; -5 | Unavailable; unavailable |

## Identity, periods and missing years

The complete series must contain two to four statements for one verified
instrument/company and one supported statement type. FY labels must be explicit
integers, consecutive and ordered oldest to newest. The calculator does not
silently sort, deduplicate or repair mislabeled years. Request validation checks
the entire selected range before network I/O; the oldest supported label is
1900 and the newest is the next calendar year, under the existing provider rule.

Each year's response must be complete, duplicate-free and classified as reported,
calculated or restated. Unknown classifications or partial responses withhold
that year's observations while retaining valid other years. Missing tags or
invalid units affect only that metric/year. An unavailable middle year disables
both of its adjacent comparisons; the calculator never jumps from the first
available year to the last or substitutes a missing value with zero.

Income/cash-flow observations require valid supplied date-only start/end and
350–378 inclusive days, retaining ordinary, leap and week-based FYs. Stub years,
missing dates or reversed windows withhold that year's observations. Comparisons
additionally require the prior period to end the day before the current starts,
and durations differing by at most seven days. Gaps, overlaps or incompatible
durations retain individually valid observations but withhold that pair's change.
Allowed duration differences are flagged without annualization or per-day scaling.

Balance sheets require supplied date-only endpoints; annual flow-start dates
are not needed. To compute adjacent annual changes, endpoints must advance by
350–378 days. Invalid endpoint spacing leaves their valid balances visible but
withholds changes. Balances are never summed across FYs.

Known differing classifications remain usable with an adjacent-pair warning.
Matching dates/units do not prove identical accounting policies, business scope,
acquisitions or one historical revision. All source cards show dates, classification,
filing/update/first-calculable metadata, retrieval time and statement/company IDs.
Currently retrieved values can contain later restatements; filing metadata does
not prove these exact values existed at an earlier date. The page makes no
historical-as-known/backtest, forecast or organic-growth claim.

## Charts and accessible tables

Each metric has a signed bar chart and exact observation/change tables. The
vertical scale is symmetric around zero and labeled ± the largest absolute
available value; each metric has its own scale. Bars use bounded integer geometry
derived from exact fractions, without rounding the source observations. Tiny
values can have subpixel bar heights; their exact values remain available in
the point readout/table. Zero has a selectable baseline point. Missing years
have no bar or point, and the charts do not interpolate or connect across them.
All-missing metrics show an explained empty chart state.

The existing locally served point script supports pointer movement/tap and
keyboard Left/Right/Home/End. It updates each chart's accessible live readout
without network requests. The chart and tables have labeled focusable horizontal
scroll containers for mobile. Templates escape text; no provider-supplied HTML
is marked safe. No chart package, CDN, Node build or new application dependency
was added.

## Provider requests, quotas and failures

One submission resolves the selected security once, then retrieves one lookup
and standardized-values response per explicitly requested annual period, oldest
first: **5 / 7 / 9 requests for 2 / 3 / 4 FYs**. These reuse existing entitled
statement endpoints and strict lookup/value identity/date/classification checks.
There are no list scans, continuation requests, prefetches or duplicate reference
lookups. Missing requested statement resources stop the entire load with an
explained 404, rather than shortening the range or choosing an earlier FY.

Every attempted HTTP call reserves the existing shared request budget of 10/client and
30/global per minute, also used by search, details, prices and other research modules.
Earlier actions can therefore exhaust a load's remaining allowance, including the
four-year view. A default seven-request load followed by another consumes at most the
remaining three before 429. The module does not grant a new quota. Invalid
fields/periods/ranges make no provider request; missing credentials are checked before
constructing transport or reserving quota.

Existing safe 404/429/503, bounded Retry-After, no-store and redacted logging apply.
A stage error clears all loaded series/chart/source context. Partial standardized
responses remain labeled without unsupported paging; their observations are
withheld. No retries, alternate periods/providers, cached responses or fallback
fixtures are used in normal application paths. Existing TLS, Decimal/JSON and
per-response bounds remain unchanged (200 rows, 256 KiB and bounded numbers).
No market-data persistence or licensing permission is inferred.

## Implementation

`AnnualStatementSeries` is an immutable provider-independent contract.
`market_data/fundamentals.py` validates range bounds; `intrinio.py` reuses one
verified identity and strict statement methods. Services reserve the shared quota.
`research/trends.py` independently validates observations, computes adjacent
changes and builds chart geometry. Forms, views and templates present the data.
Comments explain full-range validation, unavailable-year boundaries and geometry.

## Limitations

Comparisons use currently retrieved annual statements and their source versions. They
are not forecasts or historical-as-known reports. Missing years are not bridged.

See [setup and checks](setup.md#automated-checks) and the [methodology
index](methodology.md) for related calculations.
