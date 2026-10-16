# Observed portfolio volatility and drawdown

**View daily returns and risk** includes daily and annualized sample volatility, maximum
drawdown, and peak/trough/recovery dates when the input requirements are met.
Calculations reuse the daily series without additional prices or writes.

## Inputs and completeness

The pure `ledger/risk.py` accepts only the `DailySeries` contract produced by
the validated consecutive-session calculation. Explicit-period cash-flow
subperiods are a separate contract and cannot become a daily risk sample.
The producer verifies the full U.S. equity session grid; the risk calculation
checks date continuity, value continuity, finite cent inputs, pre-flow value
reconciliation and the displayed return/cumulative metadata against exact factors.
It imports without Django initialization and makes no database/network calls.

The existing 90-calendar-day, two-instrument, completed-session, raw-price,
cash-flow timing, request and correction policies apply unchanged; see
[daily return rules](daily-returns.md). All required session returns must be
valid. A missing close, invalid row or undefined opening withholds all risk
metrics and the drawdown chart. Available rows are not dropped to create a
smaller apparently complete sample. The page labels the number of requested
session-return rows, including when the series is unavailable.

## Volatility

For each complete session, use its unrounded simple return:

```text
r[i] = (ending value - net EOD external flow) / opening value - 1
mean = sum(r[i]) / n
sample variance = sum((r[i] - mean)^2) / (n - 1)
daily sample volatility (%) = sqrt(sample variance) * 100
annualized volatility (%) = sqrt(sample variance * 252) * 100
```

Daily sample volatility requires at least **two** returns. Annualized volatility
requires at least **twenty**, an explicit product sample floor rather than a
claim of statistical sufficiency. The **252-session convention** is an assumed
scale, not the actual session count of every year. Its usual interpretation
depends on the behavior of session returns, including dependence over time.
It does not forecast a year's realized risk or annual investment return.
Weekend/holiday close-to-close intervals count as one trading-session return.

Mean and variance remain exact Fraction values. The square root uses a local
80-digit Decimal context, followed by four-decimal half-up percentage formatting.
The annualized calculation scales unrounded variance, not displayed daily
volatility. No floating-point monetary/statistical calculations are used.

Two returns of +10% and −10% have a 0% arithmetic mean and sample volatility
**14.1421%**, not the population standard deviation of 10%. Twenty alternating
+100%/−50% returns have variance `11.25/19`; daily sample volatility is
**76.9484%** and annualized volatility **1221.5176%**. These are synthetic
calculation checks, not investment results. Returns that both display as 0.0000%
can still produce 0.0001% sample volatility because the input factors are unrounded.

## Drawdown and episodes

Normalize the opening close to wealth 1 and multiply the unrounded daily factors.
This removes external funding from the wealth curve. A deposit cannot create
an artificial recovery and a withdrawal cannot create an investment drawdown.
Capital changes can still affect later cash/holding weights and resulting returns.

```text
wealth[0] = 1
wealth[i] = wealth[i-1] * (1 + r[i])
peak[i] = max(wealth[0], ..., wealth[i])
drawdown[i] = (wealth[i] / peak[i] - 1) * 100
maximum drawdown = largest positive loss magnitude across the window
```

Point drawdowns range from 0% to −100%; the summary reports maximum drawdown
as a positive loss percentage. The opening baseline is a possible peak. A
single complete return supports drawdown even though sample volatility is
undefined. Terminal total loss can produce a 100% drawdown. Zero opening wealth
or an undefined restart makes the entire risk sample unavailable.

The first deepest episode is retained when depths tie. Equal repeated high
watermarks use the most recent date before a subsequent decline. The summary
shows that episode's peak and first deepest trough, and the first later session
reaching the episode's peak wealth. A later deeper decline replaces the episode
and resets its recovery. Recovery can occur before another shallower decline;
the recorded recovery still describes the selected worst episode. When there
is no drawdown, episode dates are absent. When it remains unrecovered, the page
says **Not recovered in this window**.

The synthetic browser portfolio buys 100 shares at $10 using its $1,000 deposit.
It has no fees or subsequent external flows:

| Session | Raw close | Total wealth | Drawdown |
| --- | ---: | ---: | ---: |
| 2020-01-02 | $10.00 | $1,000 | 0% |
| 2020-01-03 | $12.00 | $1,200 | 0% |
| 2020-01-06 | $9.00 | $900 | −25% |
| 2020-01-07 | $12.00 | $1,200 | 0% |
| 2020-01-08 | $9.60 | $960 | −20% |

Daily sample volatility is **28.9756%**. The maximum drawdown is **25%**, with
January 3 peak, January 6 trough and January 7 recovery. The complete return
is −4%. Four returns are insufficient for this product's annualized-volatility
display. A portfolio falling from $100 to $90 and then receiving cash remains
at a 10% return drawdown when subsequent investment return is zero, even if
its dollar balance exceeds $100.

## Presentation

`ledger/risk_chart.py` converts the already calculated values into SVG coordinates.
Calendar dates determine horizontal positions. The vertical scale fits drawdown
with at least a one-percentage-point span so a flat series is visible. Display
coordinates never feed accounting or risk calculations. The local existing
`research/prices.js` supports hover/tap inspection and focused points with
Left/Right, Home and End; a table provides all exact displayed values. No CDN
or new script dependency is required. Private response/CSRF/ownership guards
also cover the rendered risk statistics and chart.

## Limitations

Results describe selected closes and the current corrected journal, not
lifetime/intraday risk or reports as previously known. Short samples can be unstable;
zero historical volatility or drawdown does not promise future stability.

See [setup and checks](setup.md#automated-checks) and the [methodology
index](methodology.md) for related calculations.
