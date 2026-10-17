# Correlation and beta

A complete benchmark comparison can show portfolio/benchmark correlation and beta. These
statistics reuse the exact matched daily returns and request no additional prices. See
[benchmark comparison](benchmarks.md) for source and session-alignment requirements.

## Definitions

Statistics use paired simple daily returns, not cumulative wealth levels or
rounded displayed percentages. The portfolio factors already remove confirmed
end-of-day deposits/withdrawals and include recorded dividends/fees. Benchmark
factors come from provider-adjusted close ratios on the exact same sessions.
For portfolio returns `p`, benchmark returns `b`, and their respective means:

```
P = sum((p − mean(p))²)
B = sum((b − mean(b))²)
C = sum((p − mean(p)) × (b − mean(b)))
Pearson correlation = C / sqrt(P × B)
beta = C / B
```

Beta is the ordinary least-squares daily-return slope **with an intercept**.
Centering the returns matters: the uncentered product ratio is a different
model. Sample covariance and variance each use the same `n−1` divisor, which
cancels in these coefficient ratios. No intercept/alpha estimate, annualized
coefficient, confidence interval or significance claim is reported.

Correlation ranges from −1 to +1 and measures linear co-movement. Beta measures
the magnitude and direction of sensitivity to the selected benchmark, so it can
exceed that range. Both are dimensionless and display four decimal places,
without percent signs. They describe this observed window and adjusted-price
proxy; they do not establish a broad-market beta or predict future returns.

| Matched return behavior | Correlation | Beta |
| --- | --- | --- |
| Portfolio returns exactly twice the benchmark's, with variation | 1.0000 | 2.0000 |
| Portfolio returns exactly negative twice the benchmark's | −1.0000 | −2.0000 |
| Constant portfolio, varying benchmark | Unavailable | 0.0000 |
| Constant benchmark | Unavailable | Unavailable |

## Sample and unavailable rules

Both statistics require **at least twenty complete matched session returns**,
which means at least twenty-one confirmed session closes. This is a product
minimum, not a guarantee of a stable estimate. The existing 90-calendar-day
window, two-instrument limit, confirmed funding rules and corrected-journal
policy remain in force. The calculator accepts at most 89 pairs and bounded
exact Fraction factors from the validated comparison producer.

Under twenty returns, the comparison's valid return/gap/chart remain available,
while both relationship coefficients are withheld with a sample explanation.
If either complete series is missing, mismatched, inconsistent or unconfirmed,
the comparison and coefficients are unavailable. The relationship panel reports
zero validated pairs in that case. No rows are dropped or bridged to manufacture
a smaller complete sample. The benchmark producer already validates the exact
chronological session grid, identity, currency, venue, pagination and provenance.

Zero benchmark return variance makes both beta and correlation undefined. Zero
portfolio variance with a varying benchmark gives a zero fitted slope but
undefined correlation. A terminal total-loss factor is a valid observation;
undefined zero-opening/restart cases are withheld by the upstream producer.
Tiny exact variation is not treated as zero simply because its displayed returns
round to zero. Short and changing samples can still give unstable coefficients.

## Exact calculations and existing privacy

Means, centered sums and ratios stay as Fractions. Beta rounds by integer
quotient/remainder at the four-place half-unit boundary. Correlation rounds its
exact rational squared magnitude using an integer square root and squared
half-unit comparison. This avoids floats and double rounding near ties.
Decimal results are constructed with an exact digit tuple, independently of
caller precision, exponent limits and traps. Rounded zero has no negative sign.

The pure `ledger/relationships.py` module has no Django, database, calendar or
HTTP dependency. `ledger/benchmarks.py` supplies the already validated paired
factors before display rounding. The page retains owner authentication, safe
private cache headers, CSRF, one materialized corrected-journal snapshot, bounded
requests and safe error handling. There is no added endpoint or background load.
Corrections restate historical results using the current effective journal and
retain the original permanent entries.

## Limitations

Correlation and beta describe the selected observed portfolio/benchmark window. They are
not forecasts, a universal market beta, or attribution of risk to individual holdings.

See [setup and checks](setup.md#automated-checks) and the [methodology
index](methodology.md) for related calculations.
