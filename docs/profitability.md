# Selected-period profit margins

Income statements show gross, operating and net margins when source observations support
them. Intrinio source tags include `totalgrossprofit` and `totaloperatingincome`;
shorter aliases are not substituted.

## Definitions

| Margin | Numerator source tag | Formula |
| --- | --- | --- |
| Gross profit margin | `totalgrossprofit` | Gross profit / revenue × 100 |
| Operating profit margin | `totaloperatingincome` | Operating income / revenue × 100 |
| Net profit margin | `netincome` | Net income / revenue × 100 |

All three use `totalrevenue` as the denominator. Numerators are the exact
provider-standardized observations, without constructing gross profit from
cost of revenue or adjusting operating/net income for taxes, interest,
noncontrolling interests, extraordinary items or industry-specific measures.
These definitions need industry context; they are not a quality score or an
investment recommendation. Values such as EBITDA, EPS or supplied percentage
tags never substitute for a missing profit observation.

Both source values must explicitly use Intrinio's `usd` unit. No statement unit
is assigned from listing currency, and unknown/scaled/share/percentage/other
currency units are unavailable without conversion. This initial implementation
supports the user's U.S. datasets; broader currencies require an explicit unit
policy. A listing in another currency does not change explicitly supplied USD
statement values.

Revenue must be positive. Zero or negative revenue leaves all margins
unavailable under this product policy. A supplied zero numerator with positive
revenue produces `0.00%`; losses retain their sign. Margins above 100% or below
−100% remain visible without clipping. Missing tags, null observations,
unsupported numbers and unsuitable units have separate explanations. A missing
numerator withholds only its margin; an unsuitable denominator withholds all
three. The raw source cards and table remain available.

## Period and completeness checks

The page's existing three-stage provider workflow verifies instrument/company
identity, statement ID/code, fiscal year and FY/Q1–Q4 against the explicit lookup
and its returned financial values. Both numbers then come from that single
income-statement object. Margins require supplied date-only start and end dates,
with start before end, plus a supported fiscal-period label. Dates are not
reconstructed from calendar quarters or fiscal-year names. The transport already
rejects future observation dates and inconsistent metadata.

Quarterly figures remain quarterly period margins. Annual figures remain the
supplied annual period margins. No multiplication by four, trailing-year
aggregation, cross-period comparison or forecast is inferred. Provider-reported,
calculated and restated classifications remain visible alongside filing,
update, first-calculable and retrieval metadata. They do not establish when this
exact version was historically available.

A partial response with a continuation cursor withholds all margins, even when
a pair of tags happens to be present. This conservative completeness policy
does not claim that an absent tag means the company never reports it. Duplicate
tags are rejected by the transport; the pure calculator also withholds ambiguous
inputs. An empty income statement shows three explained unavailable margins.
Other statement types have no margin panel.

## Exact calculation and display

Source JSON numbers retain Decimal precision. The calculator converts them to
exact rational numbers, divides without intermediate rounding, multiplies by
100, and rounds the final percentage to two decimal places, half up. Positive
and negative halfway values round away from zero. Displayed zero has no negative
sign. This calculation and its final Decimal construction do not depend on the
caller's Decimal precision, exponent bounds or arithmetic traps. Raw financial
observations remain unrounded and unscaled.

Independent examples:

| Revenue | Gross profit | Operating income | Net income | Result |
| --- | --- | --- | --- | --- |
| 200 USD | 80 USD | 30 USD | −5 USD | 40.00%, 15.00%, −2.50% |
| 3 USD | 1 USD | −1 USD | 2 USD | 33.33%, −33.33%, 66.67% |
| 100 USD | 1.005 USD | −1.005 USD | 0 USD | 1.01%, −1.01%, 0.00% |
| 0 USD | 80 USD | 30 USD | −5 USD | All unavailable |

## Implementation boundaries

`research/profitability.py` is independent of Django, storage and HTTP.
`research/fundamentals.py` supplies its results to the existing statement view;
`research/templates/research/profitability.html` displays formulas, source tags, period
scope and unavailable reasons. Calculations add no provider request and spend no extra
quota: the statement submission still uses at most three requests under the shared
request budget, with no retries/prefetch/fallback fixtures.

Existing input validation, no-store responses and safe HTTP 404/429/503 behavior remain
in place. Provider failures never leave a margin panel on an error page. Provider
publication, retention, display rights and account quotas apply.

## Limitations

Provider publication, retention and display rights must be checked for the intended
audience. Margins describe the selected reported period, not forecasts.

See [setup and checks](setup.md#automated-checks) and the [methodology
index](methodology.md) for related calculations.
