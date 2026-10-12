# Daily portfolio session returns

Version 0.15 adds **View daily returns** on a private USD portfolio. Choose
opening/closing dates, confirm the cash-flow timing and share basis, and
**Load daily returns**. GET, including query flags, requests no market data.
The POST is protected by ownership, active-account, CSRF and no-store guards.

## Sessions and scope

The opening date is a baseline including all its activity. Every subsequent
row compares consecutive U.S. equity session closes, including Friday to Monday
or across a holiday. Closed-market dates get no fabricated zero-return rows.
Opening and closing dates must be completed sessions from 2000 onward, covering
at most 90 calendar days inclusively. Completion uses the journal's Toronto date
and requires a date before today plus an explicitly confirmed provider close.

The free `exchange-calendars==4.13.2` XNYS regular-session calendar supplies
holidays, early closes and known exceptional closures. Tests include September
11, 2001; Juneteenth 2022; and January 9, 2025. This grid applies to the existing
supported U.S. equity venues; foreign or mixed session calendars are unsupported.
Calendar rules are versioned software, not a guarantee of future emergency
closures. Updating them requires reviewing those tests and current exchange rules.

This justified dependency adds NumPy, pandas and calendar/time-zone helpers to
the frozen lockfile, with package hashes. It needs no hosted service, API key,
additional paid dataset, browser package, CDN or new network destination.
Monetary calculations still use Decimal and exact Fraction, never floating point.

## Journal and timing

One owner-scoped effective journal snapshot supplies every session's cash and
FIFO holdings. It includes explicit corrections known now, so past returns may
be restated. Original journal/audit records remain unchanged. This is not
historical reporting as known at a past recording time.

Only DEPOSIT and WITHDRAWAL are external flows. After the opening date they must
follow all other activity on the same date and be confirmed as end-of-day flows.
The existing limit of 16 opening, closing and cash-flow boundary dates applies.
Intraday funding and activity on non-session dates are rejected before price
loading. They are not silently moved to another session. Opening-date funding
is already part of the baseline. Earlier activity and later valid entries do
not enter measured returns; the full journal is still validated for integrity.

Buys, sells, fees, dividends and recorded splits remain internal. Execution prices
are journal inputs; market valuation uses raw closes. Recorded split quantities
must match those closes. Adjusted prices would count recorded actions again and
are ignored, including as a fallback for missing raw values.

## Requests and completeness

At most two instruments held at any session close across the period are supported,
including holdings sold before the end. Three instruments fail preflight before
partial fetching. Each required instrument loads one bounded history action using
the existing Intrinio adapter: at most four pages, 100 records per page and an
eight-request maximum across the action. Each page also spends the shared
10-per-client/30-total process budget. A rate limit stops later instrument loads.
Most 90-day daily histories fit one page, but provider pagination is not assumed.

Cash-only series request no prices. A position bought and fully sold within one
session does not require its close; its realized result is already in cash.
No prices are cached or persisted while licensing remains unverified. A repeat
confirmed load spends quota again; there is no polling, retry loop or auto-refresh.

An entire history must match its requested range, have complete pagination,
unique dates within that range, and no more than 90 daily observations. The
adapter rejects exchange venue changes between pages as well as currency changes. Its daily
quotes must match stable instrument ID, USD and a consistent supported stored
venue, have an aware retrieval time, and contain a finite valid raw close with
`intraperiod=False`. Every open holding needs a close on that session.

Missing required prices produce unavailable valuations and invalidate both
adjacent return rows. Available rows remain inspectable, but a single invalid
row withholds the complete-period return. No earlier-close substitution, adjusted
fallback, interpolation, zero imputation or gap bridging occurs. A known zero
close remains a valid observation. A zero opening portfolio value makes that
row undefined; later funding does not erase the gap. Required negative pre-flow
wealth also makes the result unavailable.

## Calculation and example

For each pair of sessions, with opening value `V0`, ending value `V1`, and signed
net end-of-day external flow `F` (deposit positive, withdrawal negative):

```text
daily factor = (V1 - F) / V0
daily percentage = (daily factor - 1) * 100
period percentage = (product of all daily factors - 1) * 100
```

Every valuation reconciles cash plus individually rounded position cents. Exact
rational factors are linked before four-decimal half-up percentage display;
displayed daily percentages are not multiplied back together.

The synthetic browser example records $1,000, buys ten shares at $10 with no
fee, and records a $50 EOD deposit on January 6, 2020. Closes are $10.50,
$12.25, $13, $14 and $15.50 for January 2, 3, 6, 7 and 8. Opening wealth is
$1,005. Friday-to-Monday wealth is $1,022.50 to $1,080, whose pre-flow ending
value is $1,030: a **0.7335%** session return. The four-session linked return
is **4.8600%**. Weekends are absent. Cash-only funding/withdrawals alone return 0%.

## Validation and next work

The module adds 35 tests: 17 pure calculation/form/calendar cases, one storage
guard case, and 17 actual PostgreSQL service/page cases. They cover independent
wealth/flow examples, actions, holidays, exceptional closures, session gaps,
positive/zero baselines, precision, history validity, limits, pagination quota,
one journal read, corrections, concurrent append visibility, privacy and safe
failures. A mock HTTPX transport exercises an actual eight-request paginated
load; it makes no live provider request.

Full PostgreSQL: **739 passed, no skips**. SQLite: **484 passed, 255 skipped**;
SQLite does not verify PostgreSQL storage or concurrency. The desktop/mobile
browser runs in its own disposable PostgreSQL database with explicit synthetic
prices, checking the example, cash-only/empty state, uncertain close, invalid
weekend date, provenance, ownership, CSRF, sign-out and keyboard table access.
The correction and prior performance browsers also pass. Ruff, Django checks,
migration drift and static collection pass. No migration or production data write
is needed for this module.

```sh
uv run --frozen --env-file .local/database-test.env python manage.py test --noinput
python3 tests/browser_daily_returns.py
```

No new live portfolio-series acceptance is claimed. Data coverage, licensing,
distributed quotas, broker reconciliation, FX, index benchmark methodology, intraday or
money-weighted returns and production operations remain separate work.
Observed [volatility/drawdown](risk.md) are implemented. [Benchmark comparisons](benchmarks.md) are implemented. [Correlation and beta](relationships.md) are implemented. [Sharpe](sharpe.md) is implemented with an explicit annual simple-rate assumption. [Selected-period profitability](profitability.md) is implemented. [Annual return on assets/equity](capital-returns.md) is implemented. [Annual revenue and earnings growth](growth.md) is implemented. Next: valuation multiples with explicit price and earnings dates.
