# Time-weighted returns with end-of-day cash flows

Open **View time-weighted returns**, choose opening and closing valuation dates, confirm
cash-flow timing and recorded share basis, and submit **Load returns**. Opening the form
makes no provider request. Returns are calculated per request, not stored as
independently editable values.

Calculations use the effective journal after [corrections](corrections.md). Historical
results can be restated; the audit does not reconstruct what was known earlier.

## Supported timing and period

Dates must increase, be completed dates in Toronto time, start in 1900 or later,
and span at most 366 calendar days inclusive. Defaults are suggestions, not
guaranteed trading dates. Opening value is the end-of-day value after all activity
on the opening date. Performance measures the interval after that opening close
through the closing date; opening-date deposits, trades and fees are already in
the baseline and are not included a second time in period performance.

Only DEPOSIT and WITHDRAWAL are external flows. Within the measured period they
must occur at end of day after all other activity. Journal sequence is checked:
any later trade, fee, dividend or split on an external-flow day rejects the period
before price requests. The user must also confirm actual end-of-day timing.
Date/order alone cannot establish an intraday timestamp. An intraday deposit
funding a same-day buy is unsupported; no beginning-of-day approximation or flow
valuation is silently invented. Choose another period with supported timing.

Boundaries are the opening date, each external-flow date in `(opening, closing]`,
and the closing date. Multiple flows on a date are netted, but the date remains
a boundary even when its net amount is zero. Closing-date flows are included;
later events are excluded from measured snapshots. Full journal validity is
checked first, so later corrupted prefixes do not become a trusted result.

Dividends, trade/standalone fees, buys and sells are internal activity. Net dividends
enter cash once and affect performance. Fees affect cash/basis as already recorded.
Splits change recorded shares without creating value; raw price and shares must
use the same date/basis. This does not prove action completeness or brokerage
reconciliation. All activity depends on the manually recorded journal.

## Definition and arithmetic

For consecutive boundaries, let `V0` be opening total value, `V1` ending total
value after that day's external flows, and `F` the ending day's net external flow
(deposits positive, withdrawals negative).

`subperiod factor = (V1 - F) / V0`

`cumulative return = product(all subperiod factors) - 1`

The next opening value includes the previous boundary's external flows. Every
value includes recorded cash plus the complete position market value. Position
values follow the existing half-up USD-cent valuation policy; ratios and factor
linking use exact Fraction arithmetic. Only displayed percentages are converted
to Decimal and rounded half up to four decimal places. Rounded subperiod returns
are never inputs to cumulative performance. Caller Decimal precision cannot
change the result; bounded dynamic precision supports long large-factor chains.

Each subperiod needs a positive opening value and nonnegative ending value before
external flows. Zero opening wealth is undefined, including after a full withdrawal.
A positive opening can finish with a valid -100% return. A total-loss factor remains
zero in the linked result even if later funding permits additional subperiods.
A final full withdrawal can still have a defined return because it is added back.

Examples with invented values, not market observations:

| Opening | Ending after flow | End-of-day flow | Return |
| --- | --- | --- | --- |
| $100 | $110 | $0 | 10% |
| $100 | $160 | +$50 deposit | 10% |
| $100 | $60 | -$50 withdrawal | 10% |
| $100 | $200 | +$100 deposit | 0% |
| $100 | $0 | -$110 withdrawal | 10% |
| $0 | $100 | +$100 deposit | Unavailable |

Two consecutive 10% subperiods link to 21%, not 20%. After the deposit example,
the next opening value is $160; an ending value of $176 gives a second 10% return.
Contributions change wealth without becoming investment gains.

## Prices, requests and unavailable states

The service materializes one owner-scoped bounded journal before any price I/O.
Every boundary's FIFO/cash snapshot comes from that list, so a later append cannot
mix new shares or flows into an earlier response. Each open security on each
boundary requires one exact-date daily-price request. Existing strict ID/USD/MIC,
confirmed period, exhausted cursor, finite raw close and retrieval timestamp checks
apply. No adjusted prices, weekend/holiday fallback, carry-forward, interpolation,
automatic polling or saved/cache quotes are added. Cash-only boundaries need no
quotes, including non-trading dates.

A load supports at most eight required prices, five holdings on any boundary, and 16
boundary dates. Preflight rejects larger or unsupported-timing plans before any quote
request. Requests spend the same shared 10/client and 30 total/minute budget as research
and journal lookup requests. A rate limit stops remaining prices and returns private 429
with Retry-After. Other provider failures return safe 503 messages. Valid missing-price
responses give 200 with explicit unavailability.

Every boundary must have a complete, reconciled valuation matching the planned
date, cash and positions. If any required valuation is missing or invalid, or an
opening value is zero, the complete-period return is **Unavailable**. Individually
valid subperiod returns remain visible but are not linked into a partial result
presented as the full period. Boundary totals, cash, shares, raw prices, exact dates
and retrieval provenance are visible. There is no freshness or live-price claim.

## Implementation

- `ledger/performance.py`: pure boundary plan, timing rules and exact return linking.
- `ledger/analytics.py`: reusable bounded journal snapshot and reference labels.
- `ledger/performance_services.py`: private snapshots, preflight and bounded quotes.
- `ledger/performance_forms.py`, `performance_views.py`, URL and template: private load flow.
- `tests/test_performance.py`, `tests/test_performance_pages.py`: independent examples
  and actual PostgreSQL boundaries, privacy, limits and failures.

## Limitations

Intraday and money-weighted returns, return annualization and FX are unsupported.
Results are based on manually supplied history, not a verified brokerage statement.
Daily risk and benchmark comparisons are available through the separate daily-return
workflow.

See [setup and checks](setup.md#automated-checks) and the [methodology
index](methodology.md) for related calculations.
