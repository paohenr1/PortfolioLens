# Methodology and limitations

Calculations use explicit dates, units, source observations and assumptions. Missing,
malformed or incompatible inputs stay unavailable. Chart coordinates and rounded display
values do not feed back into financial arithmetic.

Portfolio analysis uses the current corrected transaction journal. A journal snapshot is
an internal consistency boundary, separate from [supplied holdings
snapshots](holdings-snapshots.md). Neither a journal snapshot nor a static holdings
list is by itself proof of actual account performance. Corrections can restate past event-date
results. Benchmark statistics do not attribute risk to holdings.

## Accounting and valuation

- [Private portfolios and PostgreSQL](portfolios.md)
- [USD transaction journal](ledger.md)
- [Transaction corrections](corrections.md)
- [Recorded dividends and stock splits](corporate-actions.md)
- [FIFO positions, cost basis, and realized sale gains](fifo.md)
- [Explicit-date portfolio valuation](valuation.md)
- [Cash-inclusive allocation weights](allocations.md)

## Portfolio performance and risk

- [Time-weighted returns with end-of-day cash flows](performance.md)
- [Daily portfolio session returns](daily-returns.md)
- [Observed portfolio volatility and drawdown](risk.md)
- [Benchmark comparisons](benchmarks.md)
- [Correlation and beta](relationships.md)
- [Sharpe with an explicit risk-free assumption](sharpe.md)

## Stock research

- [Historical daily prices and charts](price-history.md)
- [Historical daily trading volume](volume.md)
- [Stock historical volatility and drawdown](stock-risk.md)
- [Company fundamentals and standardized statements](fundamentals.md)
- [Selected-period profit margins](profitability.md)
- [Annual return on average assets and equity](capital-returns.md)
- [Annual revenue and earnings growth](growth.md)
- [Selected-year earnings valuation multiples](multiples.md)
- [Annual financial statement trends](trends.md)
- [Dated company market capitalization](market-capitalization.md)

## Accounts, watchlists and provider data

- [Accounts and authorization](authentication.md)
- [Private watchlists](watchlists.md)
- [Watchlist market information and saved preferences](watchlist-market.md)
- [Intrinio market-data integration](intrinio.md)

## Interpreting results

Valuation supports up to five open instruments. Daily portfolio returns and risk support
two instruments across a maximum 90-calendar-day window. Their price, cash-flow and
sample requirements can leave a result unavailable even within these bounds. Period
time-weighted returns have separate boundary/request limits.

Recorded trades, corporate actions and cash flows are supplied by the user.
Provider-adjusted prices do not independently establish a total-return method.
Selected-period research ratios are not forecasts; historical volatility, beta and
Sharpe do not promise future behavior. Coverage and data-use rights must be verified for
the intended instruments and audience.
