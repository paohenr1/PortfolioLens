# Product scope

PortfolioLens supports stock research and review of private, transaction-based USD
portfolios. Its current capabilities are described in the [usage guide](usage.md). The
application provides research calculations and does not execute orders, connect to
brokerage accounts or produce tax statements.

## Current capabilities

- Instrument search, price/volume history, stock risk and company financial analysis.
- Private CSV validation, explicit instrument matching and saved dated holdings snapshots.
  Explicit loads show exact-date value, cash-inclusive allocation and concentration,
  with browser printing/PDF saving of the loaded review.
- Private watchlists with saved preferences and on-demand market information.
- Transaction accounting, explicit corrections, dividends/splits and FIFO positions.
- Dated valuation and allocations, supported time-weighted/daily returns and risk.
- Optional benchmark comparison, correlation, beta and assumed-rate Sharpe.

## Current constraints

Transaction portfolios require manually recorded transaction history. Valuation supports five open
instruments on the selected date. Daily-return/risk analysis supports two instruments
held across a maximum 90-calendar-day window, including positions sold during the
period. Supported cash-flow timing, exact prices and sufficient observations are
prerequisites, not optional quality checks.

[Methodology](methodology.md) defines source semantics, formulas and unavailable states.
Benchmark correlation is not holding-level risk attribution. Historical calculations use
the current corrected journal, not a reconstruction of what was known at the time. No
synthetic market data appears in normal operation.

## Proposed direction

The holdings-input workflow saves snapshots and supports a bounded on-screen review.
Holding-level risk attribution, stress testing and server-generated report exports remain proposals
without implemented UI or a delivery commitment.

Snapshot diagnostics keep explicit as-of dates, raw-price/USD bases, coverage
and assumptions. A snapshot alone cannot establish actual account performance;
historical returns require appropriate transaction and cash-flow history. Future
diagnostics must preserve that distinction.

The [holdings-import and snapshot-review proposal](proposals/holdings-import.md)
defines the input rules, implemented import and review calculations.
See [snapshot storage](holdings-snapshots.md) for current behavior and limits.
