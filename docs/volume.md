# Historical daily trading volume

On **View price history**, choose dates, price basis and the independent **Volume
basis**, then **Load prices**. The same bounded daily response supplies prices, stock
risk and volume. Raw volume is the default, including older saved price URLs without the
new field. The initial form still suggests 90 days ending on the prior UTC day; no load
occurs until submission. Changing fields alone makes no request.

## Source fields and units

| Basis | Intrinio field | Definition |
| --- | --- | --- |
| Raw volume | `volume` | Number of shares exchanged during each daily period |
| Adjusted volume | `adj_volume` | Provider-supplied number of shares exchanged, adjusted for splits and dividends |

Intrinio's official [StockPriceSummary documentation](https://github.com/intrinio/python-sdk/blob/master/docs/StockPriceSummary.md)
and [SDK model](https://github.com/intrinio/python-sdk/blob/master/intrinio_sdk/models/stock_price_summary.py)
were inspected for this module. Both fields are documented as numbers rather
than integer-only counts. JSON parsing retains exact Decimals; fractional raw
and adjusted values are preserved without truncation or rounding to integers.
The adjusted definition is the vendor's description, not an independently
reconstructed adjustment methodology or an observed raw count.

Volume uses shares or provider-adjusted shares, not trading currency, dollar
turnover or a liquidity estimate. No close × volume estimate, volume total,
average, ratio, forecast or portfolio activity is calculated. Price and volume
bases are independent: adjusted price does not automatically select adjusted
volume. Missing adjusted volume never falls back to raw, or vice versa.

Both fields are optional: omitted/null means unavailable without changing the
existing price-only contract. Known zero remains zero. A supplied value must be
a finite, nonnegative JSON number, at most 1e18, with at most 36 coefficient
digits and exponent between -18 and 18. These are implementation bounds, not
vendor coverage promises. Booleans, strings, negative/nonfinite numbers and
overlarge representations fail the complete response as malformed, including
when that field's basis was not selected. They are not silently treated as null.
This strict shared response validation also applies to price-only consumers.

## Coverage and presentation

Only `frequency=daily` and `intraperiod=false` observations are plotted. Unknown
or incomplete period status is excluded from bars but retained with its supplied
values in the table. Missing selected volume produces no bar or point; known
zero has a selectable point on the zero baseline. Empty/missing coverage has an
explicit unavailable state, including when prices or risk statistics are usable.
Volume can be available even if selected prices are absent; its point script
still loads in that case.

Bars use actual calendar spacing, a zero baseline and a fitted maximum. A known
all-zero series uses a one-share vertical span. Fraction arithmetic produces
bounded integer geometry; dense year-long bars have a minimum one-pixel width
without aggregating observations. Very small relative values can round to the
baseline in pixel geometry. Axis labels use four significant digits; exact
unrounded values remain in point readouts and the newest-first table. Geometry
is never used as a financial input.

Missing/absent dates are not synthesized, connected, interpolated or zero-filled.
The volume chart does not infer a trading calendar or diagnose missing sessions,
so exhausted pagination alone cannot establish full market coverage. The
separate [stock risk](stock-risk.md) panel applies its own full-session policy to
selected prices, not volume. Partial price pagination also labels volume partial;
completed supplied bars remain visible, with a suggestion to narrow the range.

The page shows both volume fields, period status, latest plotted volume/date,
plotted count, selected basis, requested range and UTC retrieval timestamp.
These daily observations do not imply a current quote or freshness guarantee.
Local `prices.js` supports independent price/risk/volume figures, pointer/touch,
keyboard focus/arrows/Home/End and live readouts, without data requests. Tables
and forms work without JavaScript; focusable horizontal regions contain mobile
overflow. One script is included once after all charts.

## Modules, requests and failures

`market_data/contracts.py` adds default-null volume fields to immutable daily
observations. `market_data/prices.py` normalizes them; the existing Intrinio
transport/paging/identity checks are reused. `research/volume_charts.py` builds
exact labels, rows and rational geometry independently of Django, persistence
and network calls. The form/view orchestrate the existing load and dedicated
`research/templates/research/volume.html` presents it.

No endpoint, request, dependency, migration, service, credential, destination
or persistence was added. The 366-calendar-day range, four pages, 100 rows/page,
shared 10/client and 30 global requests/minute, fixed HTTPS host, verified TLS,
timeouts, response limits and no-retry policy apply. Per-page quotas and safe
404/429/503 behavior remain unchanged. Failures discard all staged price/risk/
volume context, retain the form, redact diagnostics and use no-store with bounded
Retry-After. Normal startup never enables fixtures or a fallback dataset.

## Limitations

Raw and provider-adjusted share counts are separate from price basis. Fractional and
observed zero volumes are preserved. Missing or unconfirmed observations do not become
zero. Adjustment methodology and feed coverage require provider verification.

See [setup and checks](setup.md#automated-checks) and the [methodology
index](methodology.md) for related calculations.
