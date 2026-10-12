# Changelog

## Hosting verification — October 12, 2026

- Read current Render Free/pricing/build/bandwidth/runtime docs after the saved
  `render.com` addition was applied. Document actual sleep, memory/CPU, usage,
  no-shell/no-job and external-traffic suspension limits, and payment-backed
  overages. Exclude its expiring, unbacked Free database from portfolio storage.
- Validate the review template against Render's official live schema. Replace
  deprecated auto-deploy configuration with `autoDeployTrigger: "off"`, and
  disable automatic preview generation. Keep the service Free and externally
  configured PostgreSQL; no service or charge was created.
- Verify Neon TLS/direct-endpoint guidance from official sources. Document a
  trusted operator-machine path for migrations, first user and backups because
  Render Free cannot execute one-off jobs or provide a shell.
- Public terms/schema verification is complete. Hosting account access, actual
  database/ingress TLS, publication, encrypted backup scheduling and hosted
  acceptance remain. Application/dependencies stay v0.31; no full suite rerun.

## Deployment preparation — October 12, 2026

- Add a commented Render Free web-service review template with external database
  settings, private access, one worker, liveness and manual deployment. It remains
  a `.template` pending current provider terms/schema verification.
- Add a native Python build with checkout-local pinned uv bootstrap, frozen
  runtime packages, production checks and static manifest validation. No database
  migrations or user creation happen during build/start. Fresh and repeated
  synthetic builds pass; actual Gunicorn smoke using the fresh packages passes.
- Diagnose Render docs access as a 301 redirect to `render.com` after the earlier
  `docs.render.com` addition was applied. Save the additional destination without
  changing existing hosts/presets. No host resource, charge or source push.
- Document the remaining account, publication, database/TLS, user, backup and
  hosted acceptance steps. The application remains v0.31; its prior 995-test
  PostgreSQL result is not a new full-suite run for this documentation/build task.

## 0.31.0 — October 11, 2026

- Add validated Gunicorn production serving and WhiteNoise compressed/fingerprinted
  static assets, pinned from PyPI. Start small and preserve shared database quotas.
  Disable implicit Gunicorn proxy trust; Django applies explicit ingress policy.
- Default production to private research access and closed registration, with
  matching navigation. Keep development's public research/registration defaults.
  Add a process-only no-store health check without database/provider traffic.
- Reject unsafe server options and missing/invalid collected assets before start.
  Add a blank production settings template and CI's actual runtime smoke command.
- Add 13 tests; focused regression 43 pass. Full PostgreSQL 995 pass; SQLite
  703 pass, 292 PostgreSQL-only skip. Actual two-worker Gunicorn smoke verifies
  scheme handling, private routes, secure cookies, gzip/static/security headers
  and safe unavailable-storage behavior. Existing shared browser journey passes.
  Ruff lint/format 215 files; setup, migration/static and normal readiness pass.
- Add only the confirmed Render documentation domain to the network draft,
  preserving Intrinio and the package preset. Terms remain unverified until that
  configuration is applied. No hosted resource, paid service, source push or live
  provider call occurred. Next: apply documentation access and verify Render terms.

## 0.30.0 — October 11, 2026

- Require shared PostgreSQL request admission in production for both Intrinio
  requests and account write attempts. Add two bounded scope rows, atomic durable
  reservations, database-clock windows, timeouts and fail-closed storage errors.
  Keep existing development memory limits; add no Redis or other service.
- Add explicit production-only HTTPS proxy trust, default off. Verify deployment
  configuration with synthetic values and actual Django checks; retain and print
  two intentional HSTS subdomain/preload advisories without silencing settings.
- Extend CI with production configuration guards and SQLite compatibility, using
  existing frozen tools and PostgreSQL. Remote workflow execution remains unrun.
- Add exclusive mode-0600 PostgreSQL exports and an actual-command restore drill
  on two owned test databases. All model/M2M and migration row digests match;
  restored sessions, permissions, private ownership, corrected FIFO accounting
  and journal immutability pass. Remove synthetic archives and both databases.
- Add 25 tests. Full PostgreSQL 982 pass; SQLite 690 pass, 292 PostgreSQL-only
  skip. Focused safeguards 25 pass; connected browser journeys pass with memory
  and shared admission. Ruff lint/format 207 files, repeated setup, additive
  migration/static and fresh normal startup pass. Development records stay empty.
- No new dependency, paid service, subscription or live provider request. Next:
  low-cost private deployment with host-specific TLS, storage/backups and rights.

## 0.29.0 — October 11, 2026

- Add a continuous disposable-PostgreSQL browser journey covering accounts,
  idempotent trades, actions, corrections/audit, FIFO, valuation/allocation,
  matching TWR/daily returns, watchlist preferences, ownership and password change.
- Fix profit margins and operating-income trends to use Intrinio's exact
  `totalgrossprofit`/`totaloperatingincome` source tags. Add two independently
  spelled regressions proving shorter names cannot replace those observations.
- Add opt-in live acceptance with a test-only request ceiling and polite pacing
  under unchanged production quotas. AAPL price/volume/risk passes; the 26-call
  follow-up verifies margins, ROA/ROE, growth, annual P/E and trends independently,
  plus Microsoft's USD/XNAS listing. Initial six calls plus follow-up total 32.
- PostgreSQL 957 pass; SQLite 677 pass, 280 PostgreSQL-only skip. Focused margin/
  trend checks 69 pass; synthetic affected browser regressions and full journey
  pass. Ruff lint/format 194 files, repeated setup, migrations/static and fresh
  normal startup pass. Development records and temporary browser DBs stay empty.
- Document acceptance evidence and limits. No new dependency, migration, paid
  service or subscription. Next: release safeguards, then private deployment.

## 0.28.0 — October 11, 2026

- Add private saved per-watchlist price/volume bases and date-added/ticker order,
  with owner checks, CSRF-protected saves and database choice constraints.
  Additive migration preserves existing lists and reference snapshots.
- Add on-demand exact-date close/volume for one to five selected instruments,
  reusing one bounded daily request per item and the existing shared quotas.
  Preserve independent basis/missing/zero/fractional semantics and row currency.
- Keep safe per-item failures; rate limits stop remaining requests and preserve
  earlier valid rows. Recheck authorization/items after network I/O without locks.
- Add 41 tests; focused regression 77 passed. PostgreSQL 955 passed; SQLite 675
  passed and 280 PostgreSQL-only skipped. Ruff lint/format 191 files; Django,
  migrations/static, repeated setup and fresh normal startup checks pass.
- Eight synthetic desktop/mobile scenarios, prior watchlist browser regression
  and isolated live AAPL raw/adjusted price/volume acceptance pass. Development
  storage stays empty; owned temporary browser databases are removed.
- No new dependency, secret, service, polling or cost. Realtime quotes, broader
  coverage, rights and deployment remain pending. Next: broader live-data and
  complete user-journey acceptance testing.

## 0.27.0 — October 11, 2026

- Add exact-date provider-reported company market capitalization with explicit
  USD tag metadata, company identity, valuation/retrieval dates and source details.
- Expose missing underlying price/share-count dates and unverified methodology;
  do not reconstruct market cap from weighted-average earnings shares.
- Add a bounded three-request backend load, shared quota reservations, strict
  unit/identity/date/value checks, no cursor following and safe no-store pages.
  Preserve observed zero and distinguish missing/null/partial responses.
- Add 30 automated tests; focused regression 105 passed. Full PostgreSQL 914
  passed; SQLite 659 passed, 255 PostgreSQL-only skipped. Seven synthetic browser
  scenarios pass desktop/mobile; live AAPL/XNAS October 9 acceptance also passes.
  Ruff lint/format 185 files; Django, migrations/static and startup pass.
- No new dependency, migration, secret, paid service or subscription. Wider
  coverage, underlying input provenance, rights and production remain unverified.
  Next: watchlist market information and saved preferences.

## 0.26.0 — October 11, 2026

- Add optional raw/adjusted volume to daily observations with strict numeric
  validation, preserving exact fractional share counts and known zero values.
- Add an independent volume basis to the existing price form; older URLs default
  to raw. Reuse the same bounded provider response, quota and error boundary.
- Add daily volume bars, exact table, source/basis/period labels and keyboard/
  pointer inspection. Missing/unconfirmed values are excluded, partial history
  stays labeled, and volume works when price fields are absent. Load the local
  inspector once after all charts; no sums, currency turnover or fill is inferred.
- Add 27 tests; focused regression 93 passed. Full PostgreSQL 884 passed;
  SQLite 629 passed, 255 PostgreSQL-only skipped. Eight volume browser scenarios,
  all stock-risk scenarios and search/details/prices pass desktop/mobile.
  Ruff checks 180 Python files; Django, migration/static and startup pass.
- Live normal-application AAPL raw/adjusted volume acceptance passed with 42
  completed observations per basis, exact table and desktop/mobile controls.
  No new API requests per load, dependency, migration, service, secret or cost.
- Wider coverage, vendor adjustment methodology, quotas, rights and production
  remain unverified. Next: market capitalization with explicit dates/currency.

## 0.25.0 — October 11, 2026

- Add stock daily/annualized sample volatility, maximum drawdown and episode
  dates to the existing price load, with explicit raw/adjusted basis and no
  additional provider request. Add interactive drawdown and exact-close/return
  tables; preserve the price chart when risk prerequisites are unavailable.
- Require every confirmed positive selected close on the supported U.S. equity
  session grid, completed dates from 2000 and at most 366 calendar days. Weekend
  endpoints use sessions inside the range. Gaps, partial pages, zero prices,
  unknown periods and unsupported venues withhold the entire risk sample.
- Use exact fractional returns/variance, a fresh Decimal context for square roots
  and final four-place half-up percentages. Require two returns for daily
  volatility and twenty for 252-session annualization. Define episode ties and
  first recovery explicitly. Suggest a 90-day window ending on the prior UTC day.
- Add 39 tests; focused regression 88 passed. Full PostgreSQL 857 passed;
  SQLite 602 passed, 255 PostgreSQL-only skipped. Eight stock browser scenarios
  and existing search/selection/price regression pass desktop/mobile. Ruff
  checks 176 Python files; Django, migration/static and fresh startup pass.
- Live AAPL raw/adjusted acceptance over August 12–October 10 passed with 42
  closes, 41 returns, volatility/drawdown, keyboard/table and responsive checks.
  Four existing-subscription API requests; no raw response/live screenshot retained.
- No new dependency, migration, service, destination, secret or paid subscription.
  Wider coverage, adjustment-method reconstruction, licensing and production
  remain unverified. Next: bounded trading-volume charts with explicit basis.

## 0.24.0 — October 11, 2026

- Add two-to-four-FY income, balance-sheet and cash-flow trends with three defined
  USD metrics per type. Show exact observations, adjacent dollar/percentage
  changes, signed interactive bars, accessible tables and per-FY source versions.
- Require verified identities, consecutive labels, explicit units, complete
  duplicate-free classified statements and compatible dates. Treat balance
  sheets as endpoint observations; compare annual flows only across adjacent
  full-year windows. Keep valid values when pair dates prevent comparisons.
- Preserve zero/negative values and exact changes; percentages require a positive
  prior base. Missing years break both adjacent comparisons without bridging,
  interpolation, fallback periods or zero substitution. Flag duration/mixed versions.
- Reuse one security and a lookup/value pair per FY: five/seven/nine requests
  under the existing shared quota. Preserve safe errors, no-store and redaction;
  a missing requested FY stops the complete load.
- Add 38 tests: 22 calculation/chart, five adapter, nine page and two form/service.
  Focused trends/growth/statements: 116 passed. Full PostgreSQL: 818 passed;
  SQLite: 563 passed, 255 PostgreSQL-only skips. Nine trend browser scenarios and
  existing statement/search/price-chart checks pass desktop/mobile. Ruff
  lint/format checks 170 Python files; Django, migration/static and repeat startup pass.
- Correct the first browser-discovered script inclusion: the shared base does
  not render a scripts block. Add an inclusion assertion and verify actual
  keyboard/pointer readouts. No new chart dependency or production fixture path.
- No new dependency, migration, paid service, persistence, destination or live
  API call. New trend live acceptance and production remain unverified.
  Next: stock-level historical volatility and drawdown with explicit price basis.

## 0.23.0 — October 11, 2026

- Add basic and diluted selected-FY P/E, each dividing a confirmed exact-date
  raw USD close by positive provider EPS in USD per share. Keep independent
  missing/null/loss states, exact inputs and final half-up two-place multiples.
- Require explicit earnings and price dates, full-year income, compatible
  instrument/currency/venue and user-confirmed share-class/split basis. Display
  source versions and distinguish current retrieved values from historical-as-known,
  trailing, forward or latest/live P/E. Do not infer outstanding share counts.
- Reuse one security, one income lookup/value pair and one single-day price
  page: at most four requests under the existing shared quota. Preserve safe
  errors, no-store, redaction and no adjusted/prior-price or EPS fallback.
- Add 41 tests: 24 calculation/alignment, five adapter, ten page and two
  form/service. Focused P/E/growth/margins/annual returns: 152 passed. Full
  PostgreSQL: 780 passed; SQLite: 525 passed, 255 PostgreSQL-only skips.
  P/E eleven-scenario and growth/capital/profitability/fundamentals browsers
  pass desktop/mobile. Ruff lint/format (164 Python files), Django, migration
  drift/static and repeated actual HTTP startup pass.
- The first full PostgreSQL attempt was blocked by a stopped container. Restart
  the recognized container without deleting data; repeat migrations/drift and
  full tests successfully. Development model counts remain zero.
- No dependency, migration, paid service, new destination or live API call was
  added. New-P/E live acceptance and production remain unverified.
  Next: bounded multi-year financial statement trends with explicit periods.

## 0.22.0 — October 11, 2026

- Add explicit annual revenue/net-income comparisons using two adjacent FY income
  statements, shared verified identities and explicit USD units. Require supplied
  full-year windows of 350–378 days with at most seven days difference, complete
  responses and known version classifications. Warn on duration/mixed versions.
- Keep exact dollar changes and earnings transitions. Percentage growth requires
  a positive prior value; zero/negative bases remain explained unavailable
  percentages. Round only the final percentage half up to two decimal places.
- Reuse one instrument lookup and two income lookup/value pairs: at most five
  requests under the existing shared budget. Keep safe stage failures, quota stops,
  no-store errors and no retries/cache/substituted periods.
- Add 44 tests: 26 pure calculations, five adapter, eleven page and two form/service.
  PostgreSQL: 739 passed; SQLite: 484 passed, 255 PostgreSQL-only skips. Growth,
  annual-return, profitability and three-statement desktop/mobile browsers pass;
  lint/format (158 Python files), Django, migration/static and HTTP startup pass.
- No dependency, migration, paid service, new destination, persistence or live
  API call. New-growth live acceptance and production remain unverified.
  Next: valuation multiples with explicit price and earnings dates.

## 0.21.0 — October 11, 2026

- Add annual return on average assets/equity with net income and two endpoint
  balance sheets. Require same verified instrument/company, exact preceding/current
  FYs, supplied boundary dates, complete data, explicit USD units and positive
  endpoints. Keep zero/loss returns and independent assets/equity availability.
- Add an explicit fiscal-year form and source-version display. Reuse one instrument
  lookup: at most seven shared-budget requests. Stop on errors without fallback,
  retries or cached statement data. Preserve the original three-request workflow.
- Share exact financial percentage rounding and compute unrounded endpoint averages
  independently of caller Decimal context. Document total-equity/net-income scope,
  period limits and historical revision uncertainty.
- Fix a pre-existing identical-split retry race found by the first full suite:
  recheck the key if unlocked preflight fails after an identical commit. Keep
  conflicting-key rejection, locked validation and immutable history unchanged.
  Add a deterministic PostgreSQL regression for that precise timing gap.
- Add 38 annual-return tests plus one PostgreSQL race regression. Final PostgreSQL:
  695 passed, no skips. SQLite: 440 passed, 255 PostgreSQL-only skips. Annual-return,
  profitability and statement browsers pass desktop/mobile; lint/format (152 Python
  files), Django, migration/static and actual HTTP startup checks pass.
- No new dependency, migration, paid service, destination, persistence or live API
  call. Annual-return live acceptance and production remain unverified.
  Next: annual revenue and earnings growth with aligned fiscal periods.

## 0.20.0 — October 11, 2026

- Add selected-period gross, operating and net profit margins to income statements.
  Require same-statement observations, valid supplied period dates, complete
  responses, explicit USD units and positive revenue. Keep zero profit, losses
  and individual missing-source explanations; no reconstructed or trailing values.
- Calculate exact rational percentages and round the final value half up to two
  decimals without floats or caller Decimal-context dependence. Preserve raw
  observations and reported/calculated/restated provenance.
- Add 29 tests: 21 independent calculator and eight statement-page cases.
  PostgreSQL: 656 passed; SQLite: 402 passed, 254 PostgreSQL-only skips.
  Profitability and existing statement browser checks pass desktop/mobile;
  lint/format (145 Python files), Django, migration/static and HTTP readiness pass.
- Reuse the existing three bounded statement requests. No new dependency,
  migration, provider call, persistence, paid service or destination is added.
  Live acceptance of margins and production remain unverified.
  Next: return on assets and equity using aligned periods and average balances.

## 0.19.0 — October 11, 2026

- Add optional daily/annualized Sharpe to confirmed private daily-return loads.
  Require an explicitly entered annual simple risk-free percentage, including
  zero, and confirmation of constant-rate/252-session assumptions. Blank skips
  Sharpe; invalid or unconfirmed assumptions fail before price requests.
- Use exact simple excess returns and sample variance, requiring twenty complete
  returns and positive volatility. Keep missing/undefined states; annualize the
  unrounded ratio by sqrt(252). Label user assumptions and dimensionless ratios.
- Share exact rational/square-root display rounding with correlation/beta.
  Preserve corrected-journal restatement and independent portfolio Sharpe when
  only the optional benchmark fails.
- Add 34 tests: 22 pure calculation/form and twelve PostgreSQL page cases.
  PostgreSQL 627 passed, no skips; SQLite 373 passed, 254 skipped. Sharpe,
  relationship and daily-return desktop/mobile browsers, lint, framework,
  migration/static and actual HTTP readiness checks pass.
- Add no quote request, dependency, migration, paid service, destination or live
  API call. Live portfolio acceptance and production remain unverified.
  Next: stock profitability metrics from verified statement units and periods.

## 0.18.0 — October 10, 2026

- Add observed Pearson correlation and OLS beta with an intercept to the
  existing private benchmark comparison, using its exact paired simple returns.
- Require twenty complete session returns. Withhold both for incomplete data or
  zero benchmark variance; a constant portfolio against a varying benchmark
  has zero beta and unavailable correlation. No rows are dropped or filled.
- Calculate centered sums with Fractions and round coefficients through exact
  integer boundaries, avoiding floats, double rounding and caller Decimal state.
  Label dimensionless coefficients, selected proxy basis and sample limitations.
- Add 33 tests: 24 pure cases and nine PostgreSQL page/journal cases. PostgreSQL
  593 passed without skips; SQLite 351 passed, 242 skipped. Relationship and
  benchmark browsers pass desktop/mobile; framework, migration, static, lint
  and actual local HTTP readiness checks pass.
- Reuse the journal snapshot and already loaded prices with no new requests,
  dependency, migration, paid service, destination or live API call. Preserve
  corrected-journal restatement, private access, CSRF and safe error handling.
- Live relationship acceptance and production remain unverified. Next: Sharpe
  with an explicitly supplied risk-free rate and annualization convention.

## 0.17.0 — October 11, 2026

- Add an optional benchmark security to the private daily-return form, with
  provider-adjusted closes on every matching completed session. Label the
  unverified adjustment methodology as a proxy basis, preserving portfolio
  raw-price/dividend/fee accounting and confirmed funding treatment.
- Calculate exact linked daily/cumulative returns and portfolio-minus-benchmark
  gaps in percentage points. Withhold comparisons for incomplete, unconfirmed,
  mismatched or undefined inputs without dropping/filling sessions.
- Add a two-line cumulative return chart with keyboard/pointer/touch inspection,
  a scrolling values table and reference/history provenance.
- Reuse one materialized journal and same-instrument prices. Optional benchmark
  uses one reference and at most one price page: ten total requests maximum,
  every request sharing quota. Remaining cursors stay incomplete; rate limits
  stop further requests. Blank selection preserves the existing workflow.
- Share pure factor validation and venue definitions between analytics modules.
  Add 42 tests: PostgreSQL 560 passed without skips; SQLite 327 passed, 233 skipped.
  Benchmark, daily, risk and price-chart browsers pass desktop/mobile; lint,
  framework, migration-drift, static and local HTTP readiness checks pass.
- Add no dependency, migration, paid service, new destination or live API call.
  Live benchmark/index methodology acceptance and production remain unverified.
  Next: correlation and beta with matched observations and explicit sample rules.

## 0.16.0 — October 11, 2026

- Add observed volatility and drawdown to the confirmed private daily-return load,
  reusing its journal snapshot/prices without additional provider requests or writes.
- Distinguish consecutive DailySeries contracts from cash-flow boundary returns.
  Reconcile dates, values and return metadata before statistics; incomplete or
  undefined series withhold every risk metric and the chart.
- Calculate sample standard deviation of exact simple returns, requiring two
  observations. Annualized volatility requires twenty and scales unrounded
  variance by the stated 252-session convention.
- Track flow-adjusted compounded wealth and its running peak. Report maximum
  drawdown, first worst episode, peak/trough and first recovery, with explicit tie,
  total-loss and zero-opening rules. Add a drawdown table and responsive SVG chart.
- Reuse the local chart script for hover/tap, adding focused-point arrow/Home/End
  controls. Keep display coordinates separate from financial calculations.
- Add 33 tests: full PostgreSQL 518 passed without skips; SQLite 302 passed,
  216 skipped. Risk/daily and existing price-chart browsers pass on desktop/mobile
  using synthetic data; lint, framework/migration/static checks pass.
- Add no dependency, migration, paid service, new destination or live API call.
  Live portfolio-risk acceptance and production deployment remain unverified.
  Next: benchmark comparison with aligned session dates.

## 0.15.0 — October 11, 2026

- Add private daily returns between consecutive completed U.S. equity sessions,
  using the corrected journal, raw closes and confirmed end-of-day external flows.
- Use the free exchange-calendars 4.13.2 NYSE calendar for weekends, holidays,
  early closes and exceptional closures. Freeze its transitive dependencies;
  continue exact Decimal/Fraction financial calculations.
- Bound periods to 90 calendar days from 2000, two instruments held anywhere
  in the window, four history pages each and 16 cash-flow boundary dates.
  Each page spends shared quota; cash-only series make no price requests.
- Reject cross-page exchange venue changes in the shared history adapter.
- Preserve missing sessions without filling or bridging gaps. Withhold adjacent
  returns and cumulative results when required valuations are incomplete.
  Reject non-session activity and unsupported intraday funding before requests.
- Add 35 tests: 485 pass on PostgreSQL without skips; SQLite passes 277,
  skipping 208 PostgreSQL-only tests. Daily, correction and performance browser
  checks pass with synthetic data on desktop/mobile; lint and framework checks pass.
- Add no paid service, database migration, network destination or live API call.
  Live portfolio-series acceptance and production deployment remain unverified.
  Next: volatility and drawdown from complete daily series.

## 0.14.0 — October 10, 2026

- Add private replacement/void workflows with reasons, signed expiring previews,
  explicit confirmation and permanent owner-only correction history.
- Retain original entries and create immutable replacement versions/audit links
  atomically. Every calculation now uses one effective-journal SQL snapshot,
  restating event-date positions, FIFO gains, valuations, allocations and returns.
- Recheck all later balances/lots and the reviewed journal version under the
  portfolio lock. Preserve idempotent retries, prohibit cross-reused keys and
  cap all stored versions. Provider failures and stale previews leave no writes.
- Add two migrations with immutable/cross-portfolio/replacement/order guards and
  upgrade preservation checks. A direct-write race caught a foreign-key lock
  conflict; the compatible guard now passes without removing integrity checks.
- Add 44 tests; 450 pass on PostgreSQL. SQLite passes 259 with 191 skipped.
  Correction, performance, valuation/allocation and watchlist browser workflows
  pass with synthetic data. Ruff, Django, migration and static checks pass.
- Add no dependency, paid service or live API call. Multi-event corrections and
  historical reports as known at recording time remain unsupported.
  Next: daily portfolio return series for risk analytics.

## 0.13.0 — October 10, 2026

- Add private watchlist create/list/detail pages, owner-only selection from
  instrument details, stable-ID bookmarks and CSRF-protected confirmed removal.
- Store minimal verified reference snapshots with explicit unknown fields and
  retrieval times. New additions use one reference request; duplicate retries,
  list views and removals use none. No quote polling or inferred currency totals.
- Enforce 50 lists per owner and 100 items per list with transactional row locks,
  database name/ID uniqueness and authorization checks before and after lookup.
- Add one watchlist migration and 36 tests, including four PostgreSQL races.
  Full PostgreSQL: 406 passed; SQLite: 255 passed, 151 skipped. Watchlist and
  performance/valuation/allocation desktop/mobile browsers pass with synthetic
  data. Lint, Django, migration and static checks pass.
- Add no dependency, paid service or live API call. Reference refresh, list
  renaming/deletion/sharing, licensing and deployment remain separate work.
  Next: journal corrections that preserve transaction history.

## 0.12.0 — October 10, 2026

- Add private explicit-period time-weighted returns for confirmed end-of-day
  external deposits/withdrawals, with same-day timing/order checks before quotes.
- Build all boundary snapshots from one immutable journal read. Subtract ending
  external flows, retain internal dividends/fees, and link exact rational factors
  before rounding displayed percentages. Keep missing/zero-baseline returns unavailable.
- Preflight limits to 366 calendar days, 16 boundary dates, five holdings per
  boundary and eight price requests under existing quotas. No earlier/adjusted
  price fallback, saved quotes or automatic polling. Stop after rate limits.
- Add 38 tests; 370 pass on PostgreSQL, while SQLite passes 252 with 118 skipped.
  Performance and existing valuation/allocation/FIFO desktop/mobile browsers pass
  with synthetic data. Lint, Django, migration and static checks pass.
- Add no dependency, migration, paid service or live API call. Intraday flows,
  money-weighted/annualized returns, daily/risk/benchmark series and deployment
  remain separate work. Private watchlists are next.

## 0.11.0 — October 10, 2026

- Add private cash-inclusive allocation weights to the same explicit-date valuation
  result, with no additional quotes, database writes or saved projections.
- Require complete, positive total value. Withhold all weights for missing prices
  and explain zero-total portfolios; cash-only portfolios show 100.00% cash.
- Use exact cent arithmetic and largest-remainder percentage rounding so displayed
  weights sum to 100.00%. Break ties by cash first, then stable security ID.
- Add 21 tests: 14 pure calculation and seven PostgreSQL page checks. The full
  PostgreSQL suite passes 332 tests; SQLite passes 231 with 101 skipped. Expanded
  valuation/allocation and existing FIFO desktop/mobile browser checks pass.
- Add no dependency, migration, paid service or live API request. Investment returns,
  sector exposure, targets/rebalancing, corrections and deployment remain pending.

## 0.10.0 — October 10, 2026

- Add private explicit-date USD market valuation and unrealized gain/loss,
  using an owner-scoped journal snapshot through that date and confirmed raw
  daily closes with matching ID, currency and venue. Exclude later actions.
- Load only on a CSRF-protected submission after a share-basis check. Limit to
  five open instruments and one price request each under existing budgets;
  stop on rate limits. No quote cache, automatic polling or adjusted-price fallback.
- Keep missing prices and incomplete portfolio totals unavailable, retain known
  position values, and show price dates/retrieval provenance. Cash-only totals
  require no quotes. Round each position once so displayed USD cents reconcile.
- Add 33 tests; 311 pass on PostgreSQL with no skips. SQLite passes 217 with
  94 PostgreSQL tests skipped. Valuation desktop/mobile browser checks and FIFO/
  action regressions pass with synthetic data. Lint/schema/static checks pass.
- Add no dependency, migration, paid service, live price call or development
  record. Manual action completeness and live valuation remain unverified.
  Allocations, investment returns, corrections and deployment remain pending.

## 0.9.0 — October 10, 2026

- Add immutable USD Dividend and Split entries using existing owner checks,
  atomic portfolio locks, ordering, capacity, reference lookup, and client keys.
- Credit manually recorded net cash dividends separately from contributions
  and realized sale gains. Leave FIFO cost unchanged; no automatic reinvestment.
- Apply explicit forward/reverse split ratios to every open lot of the stable
  security ID. Preserve cash, total cost and previous cost allocations. Reject
  conversions requiring more than six share decimals or cash-in-lieu, including
  per-lot fractions that an aggregate-only check would miss.
- Extend PostgreSQL constraints with nullable split terms and migrate existing
  cash/trade rows without rewriting them or disabling the immutability trigger.
- Add 24 tests (278 total passing on PostgreSQL) covering independent examples,
  split-after-partial-sale conservation, provider failures, private forms,
  constraints, concurrent duplicate splits, and populated upgrade preservation.
  An isolated desktop/mobile browser workflow also passes with synthetic data.
- No new dependency, paid service, automatic corporate-action feed, live API
  call, or development record was added. Corrections, cash-in-lieu, return of
  capital, transfers, taxes, market valuations and returns remain pending.

## 0.8.0 — October 10, 2026

- Add read-only private positions and realized-sale pages, rebuilt from the
  existing immutable USD journal without provider calls or persisted totals.
- Use FIFO by transaction date and same-day order, matching stable security IDs.
  Capitalize buy fees; subtract sell fees from proceeds; show standalone fees
  separately without deducting them again from realized sale gains.
- Allocate each lot's cumulative sold cost to cents with exact rational
  arithmetic and half-up rounding. Preserve its entire original cost, including
  final sales and fractional quantities, independent of partial-sale batching.
- Display open/consumed lot provenance, signed realized gains/losses, latest
  stored reference labels, explicit USD units, and independent 25-row pagination.
  Invalid or oversized journals show an unavailable state rather than totals.
- Add 33 tests (254 total passing on PostgreSQL) and a two-user desktop/mobile
  browser workflow with synthetic trades/reference data. No new dependency,
  migration, paid service, live provider call, or development record was added.
- Market value, unrealized gains, allocations, returns, corrections, dividends,
  splits, transfers, and tax adjustments remain separate work.

## 0.7.0 — October 10, 2026

- Add a private append-only USD transaction journal for deposits, withdrawals,
  buys, sells, and standalone fees. Dates use Toronto's current calendar day;
  explicit same-day order determines historical cash and share availability.
- Keep accounting in a pure Decimal module. Round positive trade notionals
  once to cents using ROUND_HALF_UP; reject negative cash and short positions
  at every historical prefix, including backdated submissions.
- Serialize writes with portfolio-row locks, scope duplicate-submit keys to
  each portfolio, and enforce immutable rows with PostgreSQL update/delete
  triggers. Bound portfolios to 1,000 entries and histories to 25 rows/page.
- Verify trade instrument identity, USD denomination, and supported U.S. venue
  through the existing Intrinio adapter. Prices remain manually entered;
  reference snapshots do not establish historical identity or execution.
- Add 41 automated tests (221 total passing on PostgreSQL) and an isolated
  two-user desktop/mobile journal browser workflow. Browser reference data is
  explicitly synthetic; normal startup never loads it. No development records,
  live provider requests, new dependencies, or paid services were added.
- Document permanent-entry limitations. Corrections, corporate actions, FIFO
  cost basis, gains, market valuations, and returns remain separate parts.

## 0.6.0 — October 10, 2026

- Add private USD portfolio creation/list/detail pages with UUIDs, owner-scoped
  queries, CSRF-protected creation, bounded pagination, and private error pages.
- Enforce case-insensitive owner/name uniqueness, nonblank names, USD currency,
  protected ownership, and a fifty-portfolio allowance with owner-row locking.
- Add explicit PostgreSQL configuration and verified production TLS requirements;
  SQLite remains available for research/accounts with portfolio unavailability.
- Add a pinned local PostgreSQL Docker helper: private socket, no TCP listener
  or container network, retained data, and separate application/test roles.
- Add Psycopg 3/binary distributions to the frozen lock and a PostgreSQL CI
  service, without a new paid service or additional Intrinio requests.
- Add 33 database/portfolio tests (180 total passing on PostgreSQL), including
  creation races, plus a two-user desktop/mobile disposable-DB browser workflow.
- Verify fresh bootstrap, repeated setup, restart persistence, development role
  privileges, and test-role isolation. Preserve the original SQLite database.

Transactions, derived holdings, valuations/returns, production database
operations/backups, and deployment remain pending. Browser test data is removed
afterward; the local socket trust configuration is development-only.

## 0.5.0 — October 10, 2026

- Add Django registration, session sign-in, POST-only sign-out, and a private
  account page that always uses the current user. Public research remains accessible.
- Add validated password changes, preserving the current session while
  invalidating other sessions; require passwords of at least 12 characters.
- Protect modifying forms with CSRF, validate login return destinations,
  mark authentication POST data sensitive, and disable private-response caching.
- Add shared per-process account-attempt limits and eight-hour idle sessions.
- Add 28 account/security tests (147 total) and an optional desktop/mobile
  browser workflow with a disposable database and two-user identity checks.
- Preserve the free Python/Django stack: no dependencies, paid services, email
  provider, or additional Intrinio requests were introduced.

Password recovery, MFA, distributed abuse controls, PostgreSQL, private
portfolios, and deployment remain pending. This is a development account
boundary, not production authentication acceptance.

## 0.4.0 — October 10, 2026

- Add an explicit fiscal-year/FY-or-quarter financial-statement workflow for
  income, balance-sheet, and cash-flow statements, with up to three requests.
- Resolve security-to-company identity and validate period/statement identity
  across lookup and standardized values. Every stage spends the shared quota.
- Preserve Decimal values, negatives, zero, missing observations, and original
  tag units independently of listing currency. Add defined metric cards and tables.
- Display reported/calculated/restated classifications, filing/update metadata,
  unknown timezones, and a clear restatement/point-in-time limitation.
- Verify the provider's `balance_sheet_statement` code and optional omitted
  standardized-financial cursor; explicitly label any indicated continuation.
- Add `verify_fundamentals`, 34 regression tests (119 total), and desktop/mobile
  fixture browser checks for all three statement types and failure states.
- Pass authenticated AAPL fiscal-2025 FY browser checks: 22 income, 30 balance,
  and 22 cash-flow rows; the balance sheet is labeled restated.

No dependencies or paid services were added. Login pages, private portfolios,
derived analytics, broader dataset coverage/licensing, and deployment remain pending.

## 0.3.0 — October 10, 2026

- Add bounded daily-price retrieval: 366-day ranges, 100 records/page, four-page
  cap, identity/currency checks, chronological normalization, and shared quotas.
- Preserve exact Decimal closes and distinguish missing values from zero.
- Add raw/adjusted date-range charts, local point inspection, and an accessible
  observation table, without new dependencies or paid services.
- Exclude incomplete/unconfirmed periods from daily-close charts, break lines
  at supplied missing closes, and label unfinished pagination explicitly.
- Add a bounded `verify_prices` command and expand the suite to 85 tests.
- Pass fixture desktop/mobile browser checks and a live one-year AAPL workflow
  with 251 completed observations, including adjusted/raw charts and the table.

Fundamentals, broader coverage, subscription quotas/licensing, private
portfolios, and deployment remain unverified or pending. No data cache or
production fixture fallback was added.

## 0.2.0 — October 10, 2026

- Add a backend-only, typed Intrinio search and instrument-reference adapter.
- Add selectable search results and reference pages with source/retrieval metadata.
- Add strict normalization, response limits, safe errors, and credential redaction.
- Bound provider requests per client and process without automatic retries or data caching.
- Expand the automated suite to 57 tests and add a fixture-only desktop/mobile browser runner.
- Add a two-request live-check command that reports missing credentials as failure.

- Verify authenticated AAPL search and instrument lookup using the cloud vault
  binding, plus live browser search/selection and responsive detail layout.

Live acceptance covers search/reference only.
Historical prices, fundamentals, private portfolios, and deployment remain pending.
No new paid service or fixture fallback was introduced.

## 0.1.0 — October 9, 2026

- Implement the Python 3.12 / Django 5.2 LTS foundation with frozen dependencies.
- Add validated environment settings and production security guardrails.
- Define the initial user model and database migration before portfolio schemas.
- Add a responsive, locally styled landing page with explicit unavailable-data states.
- Add 21 tests for configuration, startup, page behavior, and user authentication.
- Configure GitHub Actions for linting, formatting, framework checks, tests, and assets.
- Document installation, environment variables, module boundaries, and known limitations.

Live data, login pages, portfolios, financial calculations, and deployment are
not implemented in this release. No new paid service was introduced.
