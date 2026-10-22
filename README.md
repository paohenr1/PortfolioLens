# PortfolioLens

PortfolioLens is a stock-research and portfolio-review application built with
Python, Django, PostgreSQL, and Intrinio. It uses server-rendered pages with
interactive charts and accessible data tables. It does not execute trades.

## What you can do

- Load dated S&P 500, Dow Jones and Nasdaq Composite index levels on the market
  homepage, with explicit observation dates and no automatic provider refresh.

- Research instruments, historical prices and volume, stock volatility and
  drawdown, company statements, margins, ROA/ROE, annual growth, selected-year
  P/E, financial trends, and dated company market capitalization.
- Check a small USD holdings CSV, explicitly match instruments, and save private
  dated holdings snapshots; load exact-date raw-close value, allocation and concentration,
  then print the loaded review or save it as PDF through the browser.
- Maintain private watchlists with saved display preferences and on-demand
  price/volume observations.
- Record USD transactions, dividends and splits; preview corrections while
  preserving the original journal and audit trail.
- Review FIFO positions, realized gains, dated market valuation, unrealized
  gains, and cash-inclusive allocations.
- Calculate supported time-weighted and daily returns, volatility and drawdown,
  with optional benchmark comparison, correlation, beta, and Sharpe.

## Portfolio workflow and limits

Create a portfolio, record funding and transactions, review positions, then load
valuation or performance for explicit dates. Results depend on your recorded
history, source coverage, and the confirmations shown on each calculation page.

| Area | Current limit or assumption |
| --- | --- |
| Holdings snapshots | Up to five USD instruments and explicit cash; 50 snapshots per account; exact-date value and concentration, not account performance |
| Accounting | Manually recorded USD transaction history; long positions and nonnegative cash |
| Valuation | At most five open instruments on the selected date |
| Daily returns and risk | At most two instruments held across a maximum 90-calendar-day window, including positions sold during the period |
| Cash flows | Performance requires the supported, explicitly confirmed end-of-day timing |
| Benchmark statistics | Portfolio-versus-benchmark relationships; no holding-level risk attribution |
| Data availability | Missing or unsuitable observations remain unavailable; no fabricated or silently filled prices |

Holding-level risk attribution, stress testing and server-generated report exports
remain proposed capabilities. A holdings snapshot alone cannot establish actual account
performance.
See [product scope](docs/product-specification.md) and the
[methodology index](docs/methodology.md).

## Quick start

Use Python 3.12, uv, and a local Docker daemon. From the repository root:

```sh
uv sync --frozen
python3 scripts/development_database.py
uv run --frozen --env-file .local/database.env python manage.py migrate --noinput
uv run --frozen --env-file .local/database.env python manage.py runserver 127.0.0.1:8000 --noreload
```

The helper runs a private local PostgreSQL database. Intrinio credentials are
optional for startup and automated tests, but required for live market data.
Configure them securely as described in [setup](docs/setup.md). Normal startup
never substitutes test fixtures. SQLite supports research/accounts and the transient
CSV checker; persisted portfolios, snapshots and watchlists require PostgreSQL.

## Documentation

- [Setup and checks](docs/setup.md)
- [Usage](docs/usage.md)
- [Market overview](docs/market-overview.md)
- [Architecture](docs/architecture.md)
- [Methodology and limitations](docs/methodology.md)
- [Intrinio integration](docs/intrinio.md)
- [Render and Neon operations](docs/render-deployment.md)
- [Contribution process](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)

The serving configuration supports private access and closed registration.
Deployment configuration, provider entitlements and data-display rights must be
verified for the intended audience; running the application does not establish
permission to redistribute market data.
