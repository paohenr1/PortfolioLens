# Company fundamentals and standardized statements

Implemented and authenticated AAPL annual workflows verified on October 10,
2026. This module displays supplied standardized observations; portfolio
accounting, forecasts, valuation ratios, cross-period growth, and financial
analytics remain separate parts.

## Workflow and provider boundary

Search for a stock, select its stable instrument ID, and choose **View company
financials**. Select income, balance-sheet, or cash-flow statement, a fiscal
year, and FY/Q1–Q4; submit **Load statement**. The initial form suggests the
previous calendar year and FY, but does not assert that this is the latest or
an available reporting period. Opening the form/changing a field makes no
provider call. Annual and quarterly periods follow the company's fiscal
calendar, not an inferred calendar-year or trailing interval.

Each submission makes at most three fixed-host HTTPS requests:

1. `GET /securities/{security_id}` resolves the issuer's `company_id`. Missing
   company identity returns an explicit unavailable state; a ticker is never
   substituted for an issuer ID.
2. `GET /companies/{company_id}/fundamentals/lookup/{statement_code}/{year}/{period}`
   selects one explicit fiscal period. Supported provider codes are
   `income_statement`, `balance_sheet_statement`, and `cash_flow_statement`.
3. `GET /fundamentals/{returned_id}/standardized_financials` fetches values for
   that statement. Company, fiscal year/period, statement code, ID, type, and
   date basis are checked against the lookup before displaying any values.

The explicit lookup avoids an ambiguous interpretation of company-list `type`
filters and extra list pagination. Actual responses use `reported`, `calculated`,
or `restated` for the fundamental's classification. Standardized financials
remain standardized even when the period classification is reported; this is
not the original as-reported filing layout.

## Metrics and units

| Card | Source tag | Definition |
| --- | --- | --- |
| Revenue | `totalrevenue` | Provider-standardized total revenue for the selected period |
| Net income | `netincome` | Provider-standardized net income for the selected period |
| Basic EPS | `basiceps` | Provider-standardized earnings per basic share for the selected period |
| Diluted EPS | `dilutedeps` | Provider-standardized earnings per diluted share for the selected period |
| Total assets | `totalassets` | Provider-standardized assets at the selected period end |
| Total liabilities | `totalliabilities` | Provider-standardized liabilities at the selected period end |
| Total equity | `totalequity` | Provider-standardized equity at the selected period end |
| Operating cash flow | `netcashfromoperatingactivities` | Provider-standardized net cash from operating activities for the selected period |
| Investing cash flow | `netcashfrominvestingactivities` | Provider-standardized net cash from investing activities for the selected period |
| Financing cash flow | `netcashfromfinancingactivities` | Provider-standardized net cash from financing activities for the selected period |

Cards display only the requested statement's relevant tags, alongside exact
values, units, source tags, and definitions. Income statements now include explicitly calculated selected-period gross,
operating and net margins; see [profitability](profitability.md) for source, unit,
period and completeness requirements. No P/E, annualization, trailing figures,
estimates or growth rates are inferred. Absent tags
and supplied null values have different unavailable descriptions; neither is
zero. The table contains all supplied standardized values, ordered by provider
sequence when known and then by tag, without reconstructing accounting totals.

JSON numbers remain Decimal. Exact values use grouping commas but no rounding,
currency conversion, scaling into millions, or floating-point arithmetic.
Negative net income/cash flows and observed zero are retained. Tag units `usd`,
`usdpershare`, and `shares` are displayed as USD, USD per share, and Shares.
Other units are shown verbatim as provider units without interpretation or
conversion (including percentages; no multiplication by 100 is assumed).
Missing units remain unavailable. The listing currency is separately labeled
and is never used to assign a statement currency.

Balance sheets describe a point in time at period end; income and cash-flow
values describe the supplied period. Missing start/end dates remain unavailable
instead of being reconstructed from the year or quarter label.

## Publication and restatement metadata

The page displays supplied SEC filing time, provider update time, first-calculable
time, and UTC retrieval time. Date-only metadata remains a date; a datetime
without a timezone is explicitly labeled timezone unavailable. Aware times are
displayed in UTC. No publication time is inferred from a fiscal-period end.

Restated and provider-calculated periods are explicitly labeled. These are the
currently retrieved values: a filing date does not prove that this exact later
version existed at that time. This module does not provide an as-of snapshot,
point-in-time backtest dataset, forecast, or original-filing reconstruction.

## Bounds and failures

Statement/period choices are allowlisted. Fiscal year is an integer from 1900
through the next calendar year, to allow company fiscal-year naming conventions;
supplied observation dates cannot be in the future. Unsupported periods and
missing observations are not forecasts or zeros.

Every stage spends the existing budget (10/client, 30 total requests/minute per
process), shared with search, reference, and price pages. A failure at any stage
discards the financial-value context. Missing statement lookup/value resources
return HTTP 404 for that fiscal period; missing instrument is a separate 404,
and no company identity is an unavailable state. Authentication/entitlement,
transport, and validation failures are safe HTTP 503 pages; rate limits are
HTTP 429 with bounded Retry-After. Forms remain available on errors.

There are at most 200 rows, 256 KiB per response, bounded names/units/IDs, and
no redirects/retries/prefetching. Duplicate/unsafe tags, inconsistent identity
or dates, malformed units, and nonnumeric/nonfinite values are rejected.
Financial numbers have absolute value at most 1e24, at most 40 significant
digits, and exponent from -18 through 24 to prevent hostile HTML expansion.
Provider sequence values are separately bounded to absolute value 1,000,000.
Existing TLS and per-request connect/I/O/streaming checks apply; the workflow
does not claim a hard whole-operation deadline.

The SDK exposes no paging parameters for standardized financials, and actual
responses may omit its optional `next_page` field. Missing/null indicates no
continuation was supplied, not that all company metrics exist. A bounded explicit
cursor marks the response partial; no unsupported continuation request is
invented, and missing tags in a partial response are clearly qualified.

No market-data persistence/cache, fallback fixtures, new dependencies, or paid
services were added. Result/error pages use Cache-Control no-store. Display,
redistribution, retention/caching rights and actual account quotas remain to be
verified before public deployment.

## Code and verification

Immutable contracts live in `market_data/contracts.py`; shared bounded fields
are in `fields.py`, fundamental validation in `fundamentals.py`, and the HTTPS
workflow in `intrinio.py`. Application services reserve quota for every stage.
Forms/views/templates orchestrate the UI; `research/fundamentals.py` presents
values and metadata independently of Django, persistence, and the network.

The module adds 34 tests, bringing that milestone to 119 (the project now has 884). They cover explicit
identity/period selection, endpoint codes, optional cursor behavior, restated
periods, exact decimals, negatives/zeros/nulls, dates/timezones, units, row bounds,
partial/empty/missing data, all-stage failures/quotas, escaping/redaction, and
the acceptance command. All pass. Both optional browser runners pass; the
fundamentals runner covers all statement types at desktop/mobile sizes with
keyboard tables and unavailable/denied/rate-limit states. Its invented values
are [test-only fixtures](../tests/fixtures/README.md), never production data.

Authenticated browser checks passed AAPL 2025 FY income (22 rows), balance-sheet
(30 rows, restated), and cash-flow (22 rows) pages, including metrics, metadata,
and desktop/mobile layouts. The final three-statement browser check used one
search plus three three-stage submissions, within the process client limit.
`verify_fundamentals` separately passed income and balance-sheet access. No
raw responses or credential values were recorded. Other companies and fiscal
periods, account quotas, coverage/freshness, and licensing remain unverified.

User authentication and private PostgreSQL portfolio metadata are now
implemented. The [USD transaction journal](ledger.md) and [FIFO positions/gains](fifo.md)
are also implemented. Recorded [dividends and splits](corporate-actions.md) are also supported.
Explicit-date [market valuation/unrealized gains](valuation.md) are implemented.
[Allocation weights](allocations.md) and end-of-day [time-weighted performance](performance.md)
are implemented. Private [watchlists](watchlists.md) and [journal corrections](corrections.md) are implemented. Bounded [daily session returns](daily-returns.md) are implemented. Observed [volatility and drawdown](risk.md) are implemented. [Benchmark comparisons](benchmarks.md), [correlation/beta](relationships.md),
[Sharpe](sharpe.md) and [selected-period profitability](profitability.md) are implemented.
[Annual return on assets/equity](capital-returns.md) is implemented. [Annual revenue and earnings growth](growth.md) is implemented. [Selected-FY basic/diluted P/E](multiples.md) is implemented. [Annual statement trends](trends.md) are implemented. [Stock volatility and drawdown](stock-risk.md) are implemented. [Daily trading volume](volume.md) is implemented. Next: market capitalization with explicit dates and currency.
