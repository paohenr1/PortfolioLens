# Sharpe with an explicit risk-free assumption

On **View daily returns and risk**, enter **Optional risk-free rate · annual simple %**
and confirm the constant-rate/252-session convention alongside the flow/share-basis
confirmation. Explicit zero is allowed; a blank rate skips Sharpe. A rate without
confirmation, or confirmation without a rate, fails before price requests.

The rate is a user assumption, not a retrieved Treasury rate or provider estimate. It
accepts −100% through +100% with up to four decimal places. No additional prices or
benchmark are required.

## Definitions and convention

For the entered annual simple percentage `A`, portfolio simple session returns
`r`, and `n` complete observations:

```
per-session risk-free return = A / 100 / 252
excess return = r − per-session risk-free return
mean excess = arithmetic mean of excess returns
sample excess variance = sum((excess − mean excess)²) / (n − 1)
daily Sharpe = mean excess / sqrt(sample excess variance)
annualized Sharpe = daily Sharpe × sqrt(252)
```

This is a constant **annual simple-rate** convention. It does not convert an
effective compounded yield, retrieve historical rates or accrue additional
calendar-day interest over weekends/holidays. Each consecutive session return
gets one identical per-session risk-free subtraction, including a session return
spanning a closure. Users must choose an assumption appropriate to this model.

Portfolio returns reuse the complete corrected-journal producer: confirmed
external funding is removed, while recorded dividends and fees remain. They use
raw closes consistent with recorded shares. The ratio uses unrounded simple
returns, not cumulative time-weighted returns or chart coordinates. Annualized
Sharpe scales the unrounded ratio, rather than its displayed daily value.
Subtracting a constant rate preserves the return variance; it changes the mean.

Ratios are dimensionless and display four decimal places without percent signs.
The annual/per-session rate and mean excess return are shown as percentages;
the latter two are rounded display values and do not enter calculations.
Negative mean excess gives negative Sharpe. Zero mean with nonzero volatility
gives a valid zero ratio, while zero volatility is undefined for every mean.

## Availability and interpretation

Both ratios require **twenty complete session returns** (twenty-one confirmed
closes) and positive sample volatility. The existing 90-calendar-day window,
two-instrument history bound and confirmed funding rules remain in force.
An incomplete, unconfirmed or inconsistent portfolio series withholds both
ratios, without dropping/filling observations. A short complete series preserves
ordinary returns but explains why Sharpe is unavailable. For a complete constant
series, the mean excess remains visible and the ratios stay undefined; no zero
or infinite denominator result is manufactured.

Sharpe depends on the portfolio series, not the optional benchmark. A benchmark
failure can leave portfolio Sharpe available while the existing provider error
status remains 503/429. Portfolio price failure leaves Sharpe unavailable.
The selected observed sample can be unstable. Square-root annualization assumes
stable return behavior without serial correlation; no autocorrelation adjustment,
confidence interval, future-return forecast or long-term guarantee is reported.

## Exact calculations and private workflow

`ledger/sharpe.py` uses exact Fraction factors validated by the daily producer,
then exact rate subtraction, arithmetic mean and sample variance. The squared
ratio stays rational. Shared `ledger/ratio_math.py` rounds square roots using
integer roots and exact squared half-unit comparisons; it also supplies the
existing relationship coefficient rounding. No float or approximate square root
enters displayed ratios. Decimal coefficients use exact digit-tuple construction
and normalized zero. Final ratio rounding is independent of caller precision.

The module has no Django, database, calendar or HTTP dependency. Form validation
happens before market requests; the view calculates Sharpe from the same result
already used for risk and benchmark comparisons. It adds no journal query or
quote request. Owner authentication, CSRF, private cache headers, bounded shared
quota and safe error/Retry-After handling remain in place. Journal corrections
restate excess returns and Sharpe, while original entries remain permanent.

## Arithmetic example

Ten alternating +100% and −50% simple returns have arithmetic mean 25% and
sample variance `11.25/19`, even though their cumulative return is zero.
With an explicit zero rate, daily squared Sharpe is `19/180` and annualized
squared Sharpe is `26.6`: displayed ratios are **0.3249** and **5.1575**.
With an annual simple 4% assumption, the per-session rate is `4/252` percent,
mean excess displays **24.9841%**, and ratios display **0.3247** and **5.1542**.
These intentionally synthetic values check the arithmetic, not plausible yields.

## Limitations

The risk-free rate is a constant user assumption. Time-varying or independently
retrieved risk-free series, confidence intervals and autocorrelation adjustments are
unsupported.

See [setup and checks](setup.md#automated-checks) and the [methodology
index](methodology.md) for related calculations.
