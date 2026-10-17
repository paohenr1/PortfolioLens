# Annual return on average assets and equity

Choose **View return on assets and equity** from instrument details or company
financials, select a fiscal year, and **Load annual returns**. Initial forms make no
data requests. Only annual FY periods are supported.

## Definitions and source observations

| Metric | Formula | Provider source tags |
| --- | --- | --- |
| Return on average assets | Net income / ((opening assets + closing assets) / 2) × 100 | `netincome`, `totalassets` |
| Return on average equity | Net income / ((opening equity + closing equity) / 2) × 100 | `netincome`, `totalequity` |

Net income is the selected annual income statement's provider-standardized
total. It is not adjusted for preferred dividends, noncontrolling interests,
interest, tax effects or sector-specific measures. Equity is provider-standardized
total equity, not a common-equity-only denominator. The equity ratio is therefore
not labeled a common-shareholder return. An alternative ROA definition using
after-tax interest is not used here.

Average means the arithmetic mean of two endpoint balances, not an average of
daily, monthly or quarterly balances. Large acquisitions or changes within the
period can make this endpoint approximation less representative. The numerator
is the supplied FY period, including a nonstandard fiscal-year length if returned.
No extra annualization or estimate of twelve months is applied.

All source observations require explicit provider `usd` units. Listing currency
does not supply a missing financial unit, and no currency conversion, scaling
or substitution from EPS, operating income or a supplied percentage occurs.
Missing tags, null values, unsupported numbers and unsuitable units have distinct
unavailable explanations. Source numbers remain Decimal; calculations use no floats.

Both opening and closing balances must be strictly positive under the initial
product policy. Zero or negative equity leaves the equity ratio unavailable,
even when its two-point average would be positive. Assets are evaluated
independently. Missing or unsuitable net income withholds both returns. With
valid denominators, zero net income gives `0.00%`, losses retain their sign,
and results beyond ±100% remain unclipped.

## Period and identity alignment

The load retrieves:

1. Annual income for the selected FY.
2. Annual balance sheet for the immediately preceding FY.
3. Annual balance sheet for the selected FY.

Every statement must carry the same verified instrument/company identity, its
expected statement code, the exact requested fiscal year and FY label. The
provider adapter checks lookup/value identity, classification and date basis
using the existing strict normalization. The pure calculator checks the
three-object alignment again.

Income must have supplied date-only start and end dates with start before end.
The opening balance-sheet date must be **the day before the income start**;
the closing date must be **the income end**. Dates are never reconstructed
from fiscal-year names, and an arbitrary nearby or earlier period is not used.
This supports shifted fiscal years, leap days and week-based calendars when
their supplied endpoints align. If a FY label represents a stub period, the
calculation remains that supplied period without extrapolation.

All three responses must indicate completeness; a continuation cursor withholds
both returns without unsupported follow-up paging. Duplicate tags are rejected
by normalization and by the calculator. Missing preceding-FY resources produce
a safe 404 instead of a return based only on closing assets/equity. Valid but
unaligned dates produce explained unavailable ratios with source dates visible.
The fiscal-year form starts at 1901 so the preceding FY is within the provider
adapter's 1900 lower bound. Existing upper-year and future-observation checks
remain in force; a future fiscal-year label does not make forecasts available.

## Rounding and independent examples

Opening and closing Decimal coefficients are averaged exactly, without rounding the
denominator or using the caller's Decimal arithmetic context. The ratio is an exact
rational number, multiplied by 100 and rounded only at presentation to two decimal
places, half up. Displayed negative zero is normalized to `0.00%`. The shared
`research/financial_math.py` supplies the same percentage rounding to the existing
profit margins, preserving their behavior.

| Annual net income | Opening/closing assets | Opening/closing equity | Result |
| --- | --- | --- | --- |
| 120 USD | 1,000 / 1,200 USD | 500 / 700 USD | Average assets 1,100; ROA 10.91%; average equity 600; ROE 20.00% |
| −120 USD | 1,000 / 1,200 USD | 500 / 700 USD | ROA −10.91%; ROE −20.00% |
| 0 USD | 1,000 / 1,200 USD | 500 / 700 USD | Both 0.00% |
| 1 USD | 1.01 / 1.02 USD | 500 / 700 USD | Exact average assets 1.015; ROA 98.52% |
| 120 USD | 1,000 / 1,200 USD | −500 / 700 USD | ROA 10.91%; ROE unavailable |

## Provenance, cost and failures

The page displays income and balance-sheet dates, net income, both endpoints,
the exact average and source tags. All three sources retain their statement and
company IDs, reported/calculated/restated classification, SEC filing,
provider-update, first-calculable and UTC retrieval metadata. Date-only and
timezone-unavailable metadata retain their existing labels.

These are currently retrieved versions. Matching period dates do not establish
one common historical revision; differing publication/update times remain
visible. No as-of snapshot, original-filing reconstruction, forecast or historical
backtest availability is claimed.

One instrument lookup is reused only within the current load. Three verified
lookup/value pairs give **at most seven requests**, each reserving the existing shared
10/client and 30/global requests per minute. The original single-statement workflow
still uses at most three requests. Recent searches or statement loads can consume the
remaining allowance; repeated annual loads within the same minute can return 429. No
separate quota, retry, prefetch, cross-request data cache or quota bypass is added.

Any provider-stage failure stops subsequent requests and discards the bundle. Safe HTTP
404/429/503 errors retain forms, no-store headers and bounded Retry-After where
applicable. No partial ratio remains on an error page. All supplied text is escaped.
Credentials stay backend-only and provider bodies are not displayed.

## Limitations

Only annual fiscal-year returns are supported. Quarterly and trailing-year ROA/ROE are
not calculated. The averages use two endpoint balances, not daily averages.

See [setup and checks](setup.md#automated-checks) and the [methodology
index](methodology.md) for related calculations.
