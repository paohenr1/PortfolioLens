# Changelog

## Unreleased

- Add explicit holdings instrument resolution and private immutable snapshot inputs,
  with atomic retry-safe saves, owner-only deletion and a 50-snapshot account limit.
  Snapshot pricing and analysis remain unimplemented.

- Add a private holdings CSV format checker with exact input previews, row-level
  errors and memory-only bounded uploads. No holdings are saved or priced.

- Use PortfolioLens in visible branding and clarify navigation to existing
  portfolio, risk and watchlist features.
- Replace stale feature labels and development-roadmap presentation with current
  capabilities and analysis limits.
- Rewrite documentation for users and contributors; preserve financial methodology
  and operational procedures while removing obsolete plans and execution logs.

## 0.31.0

- Add Gunicorn serving, compressed/fingerprinted WhiteNoise assets, production
  configuration validation and a process-only health endpoint.
- Default production to private access and closed registration.
- Add a native Render build and reference deployment template with manual
  deployment and automatic previews disabled.

## 0.30.0

- Add shared PostgreSQL admission for market-data and account-write requests.
- Add explicit production HTTPS proxy trust and configuration checks.
- Add private PostgreSQL exports and isolated backup/restore verification tooling.

## 0.29.0

- Correct Intrinio profit fields to `totalgrossprofit` and `totaloperatingincome`.
- Add a continuous synthetic account/portfolio acceptance journey and bounded
  opt-in live research checks.

## 0.28.0

- Add private watchlist price/volume preferences, ordering and exact-date market
  information for up to five selected instruments.

## 0.27.0

- Add exact-date provider-reported company market capitalization with source
  units, dates and explicit missing-input provenance.

## 0.26.0

- Add raw and provider-adjusted volume charts/tables with independent basis
  selection and explicit zero, fractional and missing-value behavior.

## 0.25.0

- Add stock volatility, annualization and drawdown from complete daily close
  samples without additional price requests.

## 0.24.0

- Add two-to-four-year statement trends with adjacent changes, source versions,
  interactive charts and exact tables. Missing years are not bridged.

## 0.23.0

- Add selected-fiscal-year basic/diluted P/E with explicit earnings/price dates
  and share-class/split-basis confirmation.

## 0.22.0

- Add annual revenue and earnings growth with positive-base percentage rules.

## 0.21.0

- Add annual ROA/ROE using aligned income and opening/closing balances.
- Fix an identical transaction retry race by rechecking committed idempotency
  keys when preflight validation fails.

## 0.20.0

- Add selected-period gross, operating and net margins with unit/period checks.

## 0.19.0

- Add optional Sharpe with an explicit annual simple risk-free rate assumption.

## 0.18.0

- Add correlation and beta for complete matched portfolio/benchmark returns.

## 0.17.0

- Add optional benchmark comparisons on aligned daily sessions.

## 0.16.0

- Add portfolio volatility and drawdown with episode dates and charts.

## 0.15.0

- Add bounded daily session returns using corrected history and the U.S. equity
  calendar, supporting two instruments over 90 calendar days.

## 0.14.0

- Add previewed transaction corrections/voids with permanent audit history,
  concurrency checks and restated derived calculations.

## 0.13.0

- Add private instrument watchlists with reference provenance and owner isolation.

## 0.12.0

- Add time-weighted returns with confirmed end-of-day external cash flows.

## 0.11.0

- Add cash-inclusive allocation weights with reconciled rounding.

## 0.10.0

- Add explicit-date valuation and unrealized gains for up to five open instruments.

## 0.9.0

- Add manually recorded net cash dividends and forward/reverse splits.

## 0.8.0

- Add FIFO positions, remaining cost basis and realized sale gains.

## 0.7.0

- Add the append-only USD transaction journal and duplicate-submit protection.

## 0.6.0

- Add private PostgreSQL portfolios with ownership and concurrency constraints.

## 0.5.0

- Add registration, sessions, password changes and private account pages.

## 0.4.0

- Add standardized company statements with source units, fiscal periods and versions.

## 0.3.0

- Add bounded historical-price retrieval, interactive charts and accessible tables.

## 0.2.0

- Add instrument search/reference pages and bounded Intrinio integration.

## 0.1.0

- Establish the Django application, configuration, templates and automated checks.
