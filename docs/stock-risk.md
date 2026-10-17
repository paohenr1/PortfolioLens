# Stock historical volatility and drawdown

Choose **View price history** on an instrument, select dates and raw/adjusted close,
then **Load prices**. Stock risk uses that same bounded response without another
provider call, dependency, migration, hosted service or retained market dataset. The
initial form suggests 90 calendar days ending on the preceding UTC day. Opening the form
or changing a field makes no request. Today remains available for the supplied-price
chart; risk requires a completed window before today, even after a market close.

## Complete session policy

Supported U.S. equity MICs are XNAS, XNYS, ARCX, BATS, IEXG, XASE, XNMS, XNCM,
XNGS, EDGX and EDGA. The free `exchange-calendars` NYSE calendar supplies their
shared regular-session grid, including holidays, early closes and extraordinary
closures. This is an explicit venue policy; other exchanges, OTC instruments
and missing MICs have unavailable statistics.

Risk dates start on/after 2000-01-01, end before today's UTC date and cover at
most 366 calendar days inclusive. Weekend/holiday endpoints use sessions inside
the window. At least two sessions are needed. No earlier opening price is fetched.
The existing chart still permits single-day/current-day ranges and dates from 1900.

The calculation verifies immutable complete `PriceHistory`, stable security ID,
aware retrieval time, bounded observation count and exactly one chronological
row for every expected session. Each selected close must be finite, strictly
positive bounded Decimal (at most 1e12, 28 digits, exponent -18 through 12), with
`intraperiod=false`. The adapter checks daily frequency, requested identity/range,
duplicates and consistent currency/MIC across pages.

Partial pagination, missing boundary/middle sessions, extra/reordered dates,
unknown/incomplete periods, missing selected closes or zero prices withhold the
entire risk sample. No row is dropped, bridged, interpolated, carried forward or
zero-filled; adjusted/raw values never substitute for each other. Supplied prices
remain in the existing chart/table. Exhausted pagination alone cannot prove coverage.

Percentages are dimensionless: missing or non-USD currency implies neither USD
nor conversion. Adjusted statistics use Intrinio's supplied split/dividend field;
the adjustment method is not reconstructed. Raw statistics retain corporate-action
effects that can appear as losses. Neither basis models holdings, flows, fees,
taxes or FX, or independently verifies total-return methodology. Retrieval time
is shown separately from session dates, with no current quote/freshness promise.

## Definitions and arithmetic

For selected closes `P[0] ... P[n]`, with `n` session returns:

| Metric | Definition and requirements |
| --- | --- |
| Daily return | `P[i] / P[i-1] - 1`; opening row has no preceding return inside this window |
| Daily sample volatility | `sqrt(sum((r[i] - mean(r))²) / (n - 1)) × 100`; at least two returns |
| Annualized volatility | `sqrt(unrounded sample variance × 252) × 100`; at least twenty returns |
| Running drawdown | `(P[i] / max(P[0] ... P[i]) - 1) × 100`, signed and nonpositive |
| Maximum drawdown | Largest percentage decline, displayed as a positive loss percentage |
| Worst episode | First strictly deepest decline; an equal-depth later episode does not replace it |
| Episode peak | Most recent equal running high preceding the trough |
| Recovery | First later session reaching/exceeding that episode peak; otherwise unrecovered |

Opening price is the initial peak: earlier/lifetime and intraday peaks are excluded.
A constant/rising series can have zero drawdown and no episode dates. One return
supports drawdown without sample volatility. Annualization assumes 252 sessions
and stationary behavior; it is a convention, not a forecast. Short samples can
be unstable. Currently retrieved historical source values may be revised.

Calculations retain exact `Fraction` inputs until the square root in a fresh
80-digit Decimal context, independent of caller precision/traps/exponent limits.
Percentages round half up at final display to four places, without negative zero.
Annualization uses unrounded variance. Selected closes retain exact decimals,
without rounding to portfolio cents. Rational SVG geometry gives bounded integer
coordinates used only for presentation.

Independent examples: 100, 110, 99 produce +10%/-10% returns, 14.1421% daily
sample volatility and 10.0000% maximum drawdown. Twenty alternating +100%/-50%
returns have sample variance 11.25/19, daily volatility 76.9484% and annualized
volatility 1221.5176%. A raw 100→50 split gives 50% drawdown while adjusted
50→50 gives zero, illustrating basis effects rather than verifying a vendor.

## Code and presentation

`research/stock_risk.py` computes immutable summaries/rows without Django,
provider or database calls. `research/stock_risk_chart.py` prepares geometry;
`research/views.py` reuses the existing bounded response. The dedicated template
shows definitions, source/basis, thresholds, unavailable reasons, episode dates,
drawdown chart and selected-price/return/drawdown table. Existing shared quotas,
safe errors, redacted logging, HTTP methods and `Cache-Control: no-store` apply.

Local `prices.js` independently supports price/drawdown figures, pointer/touch
inspection, point focus, arrows and Home/End, without data requests. Forms/tables
work without JavaScript. Focusable scroll regions contain mobile overflow. The
drawdown axis fits observed loss with at least a one-percentage-point span.

## Limitations

Results describe the selected complete historical close series. They do not establish
intraday risk, future stability, broader feed coverage or the provider’s adjustment
methodology.

See [setup and checks](setup.md#automated-checks) and the [methodology
index](methodology.md) for related calculations.
