# Using PortfolioLens

## Start a private portfolio

Sign in, open **My portfolios**, and create a USD portfolio. Registration may be closed
on a private deployment. Existing accounts can change their password in **My account**;
self-service password recovery is not implemented.

Open **View transactions** and record funding, trades, fees, net cash dividends and
splits in their correct date/order. The application does not import broker history or
place orders. Recording only today's holdings is insufficient for historical account
returns. Read the [journal rules](ledger.md) before entering transactions with cash
flows or corporate actions.

For a mistake, choose **Correct** or **Void**, enter a reason, preview the effects, and
save. Originals remain in the audit trail. Corrections can restate earlier valuations
and returns; they do not reconstruct a report as previously known.

## Review positions and value

**View positions and gains** shows cash, open FIFO lots, remaining cost basis, and
realized sale gains without market-data calls. Buy fees enter cost; sell fees reduce
proceeds. Check recorded dividends and splits against your records.

**View market valuation** loads raw closes for a completed date after confirming
share-basis compatibility. It supports five open instruments on that date and includes
cash in allocation weights. Missing prices leave totals and weights unavailable. This is
a dated valuation of recorded history, not broker reconciliation or a tax statement.

## Review performance and risk

**View time-weighted returns** uses explicit dates and confirmed end-of-day external
flows. Unsupported funding timing or missing boundary values prevents calculation. Its
request bounds differ from daily analysis; see [time-weighted returns](performance.md).

**View daily returns and risk** supports two instruments held across a maximum
90-calendar-day window, including holdings sold before the end. It uses completed U.S.
equity sessions. The same load supplies volatility and drawdown when the sample is
complete and sufficient.

Optional inputs on that page:

- A benchmark provider instrument ID enables an aligned comparison and, with
  sufficient matched observations, correlation and beta.
- An explicit annual simple risk-free rate and confirmation enables Sharpe.
  Leaving the rate blank skips Sharpe; zero must be entered explicitly.

Correlation and beta describe the portfolio relative to the selected benchmark. They do
not attribute risk to individual holdings. Historical risk statistics are descriptive
and do not predict future results. See the [methodology index](methodology.md) for
formulas and sample thresholds.

## Research stocks

Search by ticker or company name and select the intended listing, checking its exchange
and currency. Instrument details link to:

- Price history, volume, stock volatility and drawdown.
- Company financial statements and selected-period margins.
- Annual ROA/ROE, growth, selected-fiscal-year P/E and statement trends.
- Company market capitalization for an exact date.

Select dates, fiscal periods and price/volume bases explicitly. Source dates, units,
versions and unavailable states remain visible. Provider-adjusted data is not a
guarantee of a particular total-return or index methodology.

## Keep a watchlist

Create a list through **My watchlists**, then use **Add to watchlist** on an instrument.
References are saved with retrieval times; they are not live quotes. Save price/volume
bases and sorting preferences, then request exact-date market information for up to five
selected instruments. Opening the list itself does not request prices.

## Check a holdings CSV

From **My portfolios**, choose **Check a holdings CSV**. Enter a name, the date
those holdings describe, and an explicit USD cash balance. Upload a UTF-8 CSV of
at most 16 KiB with this header and up to five holdings rows:

```csv
ticker,exchange_mic,quantity,currency
```

Each row needs a ticker, supported U.S. exchange MIC, positive quantity (up to six
decimal places), and `USD`. The page lists supported MICs. Use plain decimal
digits without signs, exponents or thousands separators. Duplicate ticker/MIC
pairs, formulas, controls and malformed rows are rejected. Header-only files
require positive cash. Dates must be completed U.S. equity sessions from 2000
through yesterday in Toronto time.

Choose **Check CSV** to see normalized inputs or row-level errors. Reselect the
file after correcting errors; it is not stored or restored on a later visit.
The check does not verify instrument identity, save holdings, create transactions
or request prices. A valid file is not a verified account balance or performance
record. Instrument matching, saved snapshots and analysis remain proposed.
