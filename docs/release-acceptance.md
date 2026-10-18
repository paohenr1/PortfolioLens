# Acceptance checks

Use isolated synthetic checks for repeatable regression testing. Live-provider and
hosted checks are separate: local success does not establish production configuration,
endpoint entitlements or data-use rights.

## Unit, integration and runtime checks

Follow [setup](setup.md#automated-checks) for the full PostgreSQL suite, SQLite
compatibility, Ruff, Django and production-configuration checks. PostgreSQL tests cover
ownership, concurrency, immutable entries, corrections and derived accounting. Do not
count SQLite skips as validation of those guarantees.

## Browser checks

The optional runners use Python Playwright and Chromium. The current scripts expect
Chromium at `/usr/bin/chromium`; adapt the test environment if needed. They are separate
from the locked application runtime. The server child uses `.venv/bin/python`. Prepare
the local PostgreSQL helper first:

```sh
python3 scripts/development_database.py
python3 tests/browser_release_journey.py
python3 tests/browser_release_journey.py --shared-limits
python3 tests/browser_smoke.py
```

The release journey exercises two users, transactions/retries, corporate actions,
corrections/audit, FIFO, valuation/allocations, performance, watchlists, ownership and
password changes. It creates a disposable database using the isolated test role and
removes it on shutdown. Provider data is explicitly synthetic.

Feature-specific `tests/browser_*.py` runners cover chart interaction, missing data,
source provenance, desktop/mobile layout and keyboard access. For example:

```sh
python3 tests/browser_daily_returns.py
python3 tests/browser_risk.py
python3 tests/browser_profitability.py
python3 tests/browser_trends.py
```

After a runner fails, inspect its diagnostics and verify cleanup of its owned
process/database before retrying. Do not terminate unrelated application processes.

## Opt-in live checks

[Intrinio commands](intrinio.md#live-acceptance-after-secure-configuration) provide
bounded endpoint checks. `tests/browser_live_research.py` additionally exercises
research pages with live data and an isolated account/database. Its default ceiling is
32 backend calls; `--financial-follow-up` has a 26-call ceiling. It paces requests under
existing quotas and does not replace transport with fixtures.

Live checks require secure credentials and applicable rights. They are not part of
ordinary startup, health probes or secret-free CI. A passing instrument/period does not
establish wider coverage, provider adjustment methodology or retention and
redistribution rights.

## Hosted acceptance

Use the [operations guide](render-deployment.md) to verify the actual branch, commit,
TLS, configuration and private workflow before a release. Synthetic runtime smoke does
not prove hosted database connectivity or recovery readiness.

## Holdings snapshot acceptance

Run `python3 tests/browser_snapshots.py` with Playwright and Chromium installed.
It uses a disposable local PostgreSQL database and synthetic Intrinio transport to
check explicit selection, confirmation, exact quantities, private save/reload,
two-user isolation, deletion, cash-only inputs and desktop/mobile layout. It makes
no live-provider requests and does not verify provider entitlements.

For the dated review, run `python3 tests/browser_snapshot_review.py`. It uses the
same isolated synthetic setup to verify explicit price loads, fixed dates, exact
values and weights, concentration, missing-price suppression, cash-only inputs,
keyboard tables and two-user desktop/mobile access. It does not establish live
provider coverage, entitlements or deployment readiness.
