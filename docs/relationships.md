# Correlation and beta

Version 0.18 adds observed relationship statistics to the optional benchmark
comparison on **View daily returns**. Enter the benchmark's provider security ID,
choose completed session dates and confirm the existing flow/share-basis rules.
The existing confirmed load produces the comparison and these statistics from
the same data. Calculating them adds no provider request, storage write,
dependency, paid service or new destination.

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

## Validation and next work

33 new tests include 24 pure calculation/comparison cases and nine PostgreSQL
page/journal cases. Independent examples cover ±2 slopes, intercept centering,
partial/irrational/zero correlations, constant-series rules, 19/20 sample gates,
tiny unrounded changes, exact beta rounding ties, caller Decimal settings,
invalid/mismatched inputs and terminal loss. Page tests verify unchanged provider
call counts and journal rows, same-instrument history reuse, missing quotes,
funding, safe rate limits and fee-correction restatement. A fee of 100 in the
20-return alternating-benchmark example has beta −11/210 (−0.0524); correcting it
to 200 gives −11/105 (−0.1048), preserving the original fee.

Full PostgreSQL: **739 passed without skips**. SQLite: **484 passed, 255 skipped**;
SQLite does not validate PostgreSQL persistence/concurrency. Relationship and
benchmark browsers pass desktop/mobile with explicit synthetic data in their
own disposable PostgreSQL databases. They cover sample/variance/missing-data
states, displayed coefficients, responsive layout, existing chart keyboard
behavior, owner isolation, CSRF and sign-out. Ruff checks 158 Python files;
Django, migration-drift, static and local HTTP readiness checks pass.

```sh
uv run --frozen --env-file .local/database-test.env python manage.py test --noinput
python3 tests/browser_relationships.py
python3 tests/browser_benchmarks.py
```

Live portfolio/benchmark acceptance, provider adjustment/index methodology,
coverage/licensing and production deployment remain unverified. The existing
selected-benchmark proxy limitations in [benchmarks](benchmarks.md) still apply.
[Sharpe](sharpe.md) is implemented with a confirmed explicit annual simple-rate assumption. [Selected-period profitability](profitability.md) is implemented. [Annual return on assets/equity](capital-returns.md) is implemented. [Annual revenue and earnings growth](growth.md) is implemented. Next: valuation multiples with explicit price and earnings dates.
