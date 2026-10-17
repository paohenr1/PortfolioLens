# Selected-year earnings valuation multiples

Selected-year basic and diluted P/E use Intrinio annual statements and historical raw
closes. Earnings and price dates, source versions and share-basis assumptions remain
explicit.

## Workflow

From instrument details or company financials, choose **View annual earnings
valuation multiples**. Enter **Earnings fiscal year**, an exact **Raw closing
price date**, confirm the listed share class and EPS/price split basis, then
**Load annual P/E**. Opening the form does not request data. Defaults suggest
the previous calendar year and yesterday; they do not promise an available FY
statement or trading day. The confirmation starts unchecked.

A company association is not proof that issuer EPS applies to a particular
listed share class, ADR ratio or split basis. The user must check those facts,
including any adjustments in the retrieved statement. Confirmation is an
assumption, displayed as user confirmed and not independently verified. The app
does not retrieve corporate actions or automatically reconcile historical EPS
and prices. If compatibility is unknown, leave the confirmation unchecked.

## Definitions and exact arithmetic

| Metric | Earnings source | Calculation |
| --- | --- | --- |
| Basic FY P/E | Annual income `basiceps`, unit `usdpershare` | Exact-date raw USD close / positive basic FY EPS |
| Diluted FY P/E | Annual income `dilutedeps`, unit `usdpershare` | Exact-date raw USD close / positive diluted FY EPS |

Both results are dimensionless multiples, displayed with **×**, not percentages.
Basic and diluted EPS remain independent observations: neither replaces the
other, and neither is reconstructed from net income and shares. Missing tags,
null values, incompatible units and unsupported numeric types have separate
unavailable explanations. Listing currency never supplies a missing EPS unit.

Calculation retains exact `Decimal` inputs as rational fractions, then rounds
only the final multiple to two decimal places, half up. It is independent of
ambient Decimal precision, exponent limits and traps. A tiny rounded result
displays `0.00×`, without negative zero. EPS must be positive; observed zero or
negative EPS remains visible but makes that P/E unavailable. A confirmed zero
raw price with positive EPS produces `0.00×` rather than an unavailable value.
No absolute denominator, clipping or earnings substitution is applied.

Examples are synthetic calculation checks, not market observations:

| Raw close | Basic EPS | Diluted EPS | Basic P/E | Diluted P/E |
| --- | --- | --- | --- | --- |
| 30 | 2 | 1.5 | 15.00× | 20.00× |
| 30 | -2 | 1.5 | Unavailable; loss EPS | 20.00× |
| 30 | 0 | 1.5 | Unavailable; zero EPS | 20.00× |
| 0 | 2 | 1.5 | 0.00× | 0.00× |
| 1.005 | 1 | 2 | 1.01× | 0.50× |

## Period, unit and price requirements

The source must be a complete FY income statement, with an explicit integer
fiscal label, valid supplied date-only start/end, no duplicate tags and a known
reported/calculated/restated classification. Inclusive duration must be
350–378 days, the same explicit product policy as annual growth. Ordinary,
leap and week-based years are supported; stub periods and quarters are not
annualized. The price date must be on or after the supplied income end date.
An earlier date leaves all ratios unavailable and explains the mismatch.

Both instrument references must match the selected stable ID, USD trading
currency and known exchange MIC. The statement must have the verified company's
ID; a company ID supplied in the price summary must agree. A missing price-summary
company field does not supply or replace the verified statement association.

Prices require a complete one-day response with exactly one matching daily
observation explicitly marked `intraperiod=false`, an aware retrieval timestamp,
and a supported nonnegative raw close. Retrieval cannot precede the price day.
Empty, partial, duplicate, uncertain, wrong-date or incompatible price sources
leave both ratios unavailable. Adjusted prices and earlier-day closes never
substitute for missing raw prices; a weekend date can therefore be unavailable.

Existing transport bounds apply: financial values have absolute value at most
1e24, at most 40 significant digits and exponent -18 through 24. Raw prices
have value 0–1e12, at most 28 digits and exponent -18 through 12. No float,
boolean, nonfinite value or arbitrary exponent is accepted as a calculation
input. A derived ratio can exceed the input amount bounds.

## Dates, versions and interpretation

The page places income start/end, FY label, inclusive days, selected price date,
usable raw close and the confirmed assumption alongside the two P/E cards. It
shows classification, filing/update/first-calculable metadata and retrieval
timestamps, plus statement/company IDs and the price instrument, venue and
currency. Unknown or timezone-free publication metadata remains explicitly
unavailable or timezone unavailable through the existing metadata formatter.

These are selected-FY P/E ratios using currently retrieved statement versions.
They are not trailing-twelve-month, forward, latest/live or historical-as-known
P/E. A price years after the selected FY can use stale earnings; the dates remain
visible, with a persistent explanation. Later-restated EPS may not have existed
on the price date, even when a filing date predates it. This workflow does not
make historical point-in-time/backtest claims or infer unchanged share basis,
accounting policies, FX, organic earnings, annualization or investment advice.

Market capitalization, P/S, P/B and enterprise-value multiples remain deferred:
they need separately verified date-specific share counts, issuer/security scope
and compatible debt/cash/equity definitions. An issuer's weighted-average EPS
denominator is not automatically the listed instrument's outstanding shares.

## Requests, failures and quotas

Every valid submission makes at most four backend HTTPS requests:

1. Resolve the instrument once through `/securities/{id}`.
2. Look up its company's explicit annual income FY.
3. Retrieve that statement's standardized financials and validate lookup/value
   identity, classification and date consistency.
4. Request one page of daily prices for the exact selected date.

The price endpoint is the existing historical daily-price route. No new endpoint, data
subscription or extra quota allowance is introduced. Each actual request reserves the
shared budget (10/client and 30/global requests/minute). Two full loads use eight
requests; a third can consume the remaining two before being blocked. Invalid fields or
a missing confirmation make no provider request. Missing credentials are checked before
constructing transport or spending quota.

Failures stop immediately with safe existing 404/429/503 pages, bounded
Retry-After and no-store headers. No loaded statement/price/ratio context survives
a stage error. Initial, result and validation pages are also no-store. A partial
price cursor is labeled incomplete without following it. There are no retries,
prefetches, fallback providers, inferred periods or cross-request caching.
Existing TLS, strict JSON, response-size and redacted logging rules apply.

## Limitations

Ratios use selected-year earnings and a selected raw close with currently retrieved
statements. They are not trailing, forward, live or historical-as-known P/E. Share-class
and split-basis compatibility must be confirmed.

See [setup and checks](setup.md#automated-checks) and the [methodology
index](methodology.md) for related calculations.
