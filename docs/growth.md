# Annual revenue and earnings growth

Choose **View annual revenue and earnings growth** from instrument details or company
financials, select the current fiscal year, and **Load annual growth**. The load
compares that annual income statement with the immediately preceding annual FY. Opening
the form requests no provider data.

## Definitions and base-value policy

| Metric | Provider source tag | Formula |
| --- | --- | --- |
| Revenue growth | `totalrevenue` in both income statements | (Current revenue − prior revenue) / prior revenue × 100 |
| Net income growth | `netincome` in both income statements | (Current net income − prior net income) / prior net income × 100 |

Dollar change is current minus prior. Both source values must explicitly use
the provider `usd` unit; listing currency never supplies a missing statement
unit. No FX conversion, scaling, EPS substitution, alternative profit adjustment,
organic-growth estimate or forecast is inferred. Net income is the
provider-standardized total, not earnings per share or income adjusted for
preferred dividends/noncontrolling interests.

Percentage growth requires a **strictly positive prior value**. A current zero
with a positive base produces −100%; a current loss can produce a percentage
below −100%, without clipping. A zero or negative prior value leaves percentage
growth unavailable, while retaining exact dollar change. No absolute-value
denominator is silently substituted for negative earnings.

Observed zeros remain distinct from missing tags and null observations. With
valid sources, the page labels increases/decreases and earnings transitions
such as loss to profit, profit to loss, loss narrowed/widened, and changes from
break-even. A missing or unsuitable source withholds only that metric; the other
metric remains available. Unsupported/nonfinite numbers, absent/null tags and
unsuitable units have separate explanations.

Independent examples:

| Prior → current | Dollar change | Percentage | Interpretation |
| --- | --- | --- | --- |
| Revenue 800 → 1,000 USD | +200 USD | 25.00% | Increased |
| Net income 100 → 120 USD | +20 USD | 20.00% | Increased |
| Net income 100 → −20 USD | −120 USD | −120.00% | Profit to loss |
| Net income −100 → −50 USD | +50 USD | Unavailable | Loss narrowed |
| Net income −100 → 50 USD | +150 USD | Unavailable | Loss to profit |
| Net income 0 → 120 USD | +120 USD | Unavailable | Break-even to profit |
| Net income 100 → 0 USD | −100 USD | −100.00% | Profit to break-even |

## Annual comparability checks

Both observations must come from income statements with consecutive fiscal-year
labels and FY periods, sharing the same verified instrument and company ID.
The adapter validates each lookup/value pair's identity, fiscal year, statement
code, period, classification and date basis. The pure calculator checks the
two-statement alignment again.

Both periods require supplied date-only start/end dates, with start before end.
The prior period must end exactly the day before the current period starts:
gaps and overlaps are unavailable. Fiscal-year names do not supply calendar
dates. Each inclusive supplied period must cover **350–378 days**, and their
lengths must differ by **at most seven days**. These explicit initial product
bounds permit ordinary and week-based FYs while withholding stub periods and
larger duration changes. They are a comparability policy, not a claim that every
FY in every dataset has those lengths. Unsupported windows remain unavailable.

A 364-day versus 371-day year is accepted with a visible duration warning.
Leap-day periods retain their observed 365/366-day lengths. Neither dollar change
nor percentage growth is adjusted per day, annualized or called a trailing-year
estimate. Quarterly comparisons, CAGR and broader statement trends are deferred.

Both responses must indicate completeness and have unique tags. Partial
responses withhold the whole comparison without unsupported continuation
requests. Missing prior-FY resources produce a safe 404; earlier years or values
from balance sheets never substitute for the requested income period.

Both statements require a known reported/calculated/restated classification.
Different known classifications retain the comparison with a visible warning;
an unknown classification withholds it. All source versions, IDs, SEC filing,
provider-update, first-calculable and UTC retrieval metadata remain visible.
Current/restated values with matching dates do not establish one historical
revision. Matching dates/units do not prove unchanged accounting policies,
business composition or acquisition effects. This is not an as-of backtest dataset.

## Arithmetic, requests and failures

Source JSON numbers remain Decimal. `research/financial_math.py` computes
current-minus-prior by aligning integer Decimal coefficients, preserving the exact
dollar change independently of caller precision/exponent bounds/traps. The percentage
uses exact rational arithmetic and is rounded only at final presentation to two decimal
places, half up. Displayed negative zero becomes `0.00%`; the raw negative dollar change
is retained. Existing margin and average-balance calculations share the same helpers and
retain their behavior.

`AnnualGrowthStatements` is an immutable provider contract.
`IntrinioClient.annual_growth` reuses one verified instrument lookup and two income
lookup/value pairs, for **at most five requests**. Every stage reserves the existing
shared 10/client and 30/global requests per minute. Recent searches/research loads can
use the remaining allowance. No new quota, cache, retries, prefetch or automatic period
substitution is added. The existing single-statement and annual-return workflows retain
their three/seven request bounds.

Any provider-stage failure stops remaining requests and discards the bundle. Safe HTTP
404/429/503 pages retain the form, no-store headers and bounded Retry-After where
applicable. No earlier calculated context remains on an error page. Invalid
year/period/identifier/method requests do not spend transport. All source text is
escaped, credentials stay backend-only and provider bodies are not shown.

## Limitations

Growth compares adjacent annual fiscal periods, not quarterly, trailing-year or forecast
results. Percentage changes require a positive prior value; loss transitions are labeled
rather than assigned misleading growth percentages.

See [setup and checks](setup.md#automated-checks) and the [methodology
index](methodology.md) for related calculations.
