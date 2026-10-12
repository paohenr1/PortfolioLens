# Test-only reference, price, and financial fixtures

These deliberately synthetic instruments are deterministic test fixtures, not
financial observations. `TSTF`, the company names, and the security IDs are
invented. They must never be used as a production fallback or included in a
public deployment. `daily_prices.json` contains deliberately invented prices
for deterministic tests of gaps, missing fields, and incomplete periods. These
values are not market observations. `fundamental.json` and
`standardized_financials.json` contain invented statement metadata and values
for testing losses, zero/missing values, units, and fiscal periods. Test-only
helpers derive other statement/quarter fixtures from these definitions. They
are not company filings or observations. Portfolio returns are not simulated.
The optional ledger browser runner reuses the synthetic security reference only
when its temporary test-server fixture flag is explicitly enabled. Its manually
entered trades and cash movements are accounting examples, not brokerage data.
Normal application startup never enables that transport or creates test entries.

The response shapes follow Intrinio's official SecuritySummary, Security,
ApiResponseSecuritiesSearch, StockPriceSummary, ApiResponseSecurityStockPrices,
Fundamental, StandardizedFinancial, and DataTagSummary
documentation. They have not been captured
from an authenticated account response.


Market-cap fixtures in `tests/test_capitalization.py` are invented company
observations and tag metadata. They follow the Intrinio CompanyHistoricalData,
HistoricalData and DataTag response shapes. They are not captured account data;
the optional browser helper injects them only into its owned test process.


Watchlist market examples in `tests/test_watchlist_market.py` and the browser
scenario adapter `tests/watchlist_market_fixture.py` use invented distinct raw/
adjusted closes/volumes, missing/zero/partial/unconfirmed rows and fixed errors.
Only the disposable browser server can opt into that adapter. Its live-acceptance
mode forbids simultaneous fixture transport and retains the real vault binding;
normal production/development startup imports neither mode.
