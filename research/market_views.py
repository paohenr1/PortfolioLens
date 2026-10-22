"""Explicit daily index-level loads for the market homepage."""

import logging
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, localcontext

from django.conf import settings
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from market_data.errors import (
    AuthenticationFailed,
    CredentialsMissing,
    ProviderError,
    ProviderRateLimited,
)
from market_data.indices import INDEX_CATALOG
from market_data.status import provider_status
from research import services, watchbar

PERIODS = {"1D": 0, "1W": 7, "1M": 30, "1Y": 365}
logger = logging.getLogger("research")


def base_context(period="1M"):
    now = datetime.now(UTC)
    return {
        "provider_status": provider_status(credential_present=bool(settings.INTRINIO_API_KEY)),
        "watchbar": watchbar.empty_watchbar(),
        "indices": [{"key": key, "name": item[2]} for key, item in INDEX_CATALOG.items()],
        "period": period,
        "periods": tuple(PERIODS),
        "today": now,
        "requested_end": now.date() - timedelta(days=1),
    }


def index_presentation(history, chart_start, *, single_session=False):
    """Changes explicitly compare supplied dates; null observations break chart lines."""
    observations = history.observations
    available = [row for row in observations if row.value is not None]
    result = {
        "key": history.key,
        "name": INDEX_CATALOG[history.key][2],
        "retrieved_at": history.retrieved_at,
        "rows": observations,
        "paths": [],
    }
    if not available:
        result["issue"] = "No usable index levels were supplied for this window."
        return result
    latest = available[-1]
    # An old observation outside the selected chart range is not a current-window value.
    if latest.date < chart_start and not single_session:
        result["issue"] = "No usable index levels were supplied inside the selected window."
        return result
    result.update(
        {
            "level": f"{latest.value.quantize(Decimal('.01'), rounding=ROUND_HALF_UP):,.2f}",
            "as_of": latest.date,
            "available": True,
        }
    )
    position = observations.index(latest)
    previous = observations[position - 1] if position else None
    with localcontext() as context:
        context.prec = 40
        if previous is not None and previous.value is not None:
            change = latest.value - previous.value
            percent = change / previous.value * 100
            result.update(
                {
                    "change": f"{change.quantize(Decimal('.01'), rounding=ROUND_HALF_UP):+,.2f}",
                    "percent": f"{percent.quantize(Decimal('.01'), rounding=ROUND_HALF_UP):+.2f}%",
                    "direction": "negative" if change < 0 else "positive",
                    "previous_date": previous.date,
                }
            )
        else:
            result["direction"] = "neutral"
        chart_rows = (
            [latest] if single_session else [row for row in observations if row.date >= chart_start]
        )
        # Include the preceding supplied observation as a baseline for the 1D view.
        if len(chart_rows) == 1 and previous is not None:
            chart_rows.insert(0, previous)
        values = [row.value for row in chart_rows if row.value is not None]
        if len(values) >= 2:
            minimum, maximum = min(values), max(values)
            span = maximum - minimum or Decimal(1)
            days = Decimal(max(1, (chart_rows[-1].date - chart_rows[0].date).days))
            segment = []
            for row in chart_rows:
                if row.value is None:
                    if segment:
                        result["paths"].append(" ".join(segment))
                        segment = []
                    continue
                x = Decimal(4) + Decimal((row.date - chart_rows[0].date).days) / days * 192
                y = Decimal(64) - (row.value - minimum) / span * 56
                segment.append(f"{'L' if segment else 'M'}{x:.2f} {y:.2f}")
            if segment:
                result["paths"].append(" ".join(segment))
    return result


def render_markets(request, context=None, status=200):
    response = render(request, "research/home.html", context or base_context(), status=status)
    response.headers["Cache-Control"] = "no-store"
    return response


@require_POST
@never_cache
def load_market_indices(request):
    period = request.POST.get("period", "")
    if period not in PERIODS:
        context = base_context()
        context["input_error"] = "Choose a supported chart range before loading."
        return render_markets(request, context, status=400)
    context = base_context(period)
    context["loaded"] = True
    end = context["requested_end"]
    chart_start = end - timedelta(days=PERIODS[period])
    query_start = chart_start - timedelta(days=10)
    results, stop_error = [], None
    status, retry_after = 200, None
    for key, (_, _, name) in INDEX_CATALOG.items():
        try:
            if stop_error is not None:
                raise stop_error
            history = services.market_index_history(
                key, query_start, end, request.META.get("REMOTE_ADDR", "")
            )
            results.append(index_presentation(history, chart_start, single_session=period == "1D"))
        except ProviderError as error:
            results.append({"key": key, "name": name, "issue": error.message})
            if error.status == 429 or isinstance(error, (CredentialsMissing, AuthenticationFailed)):
                stop_error, status, retry_after = error, error.status, error.retry_after
        except Exception:
            logger.exception("Unexpected index overview failure")
            results.append({"key": key, "name": name, "issue": ProviderError.message})
            stop_error, status = ProviderError(), 503
    context["indices"] = results
    watch = watchbar.load_watchbar(
        request.META.get("REMOTE_ADDR", ""),
        stop_error=stop_error if isinstance(stop_error, ProviderRateLimited) else None,
    )
    context["watchbar"] = watch.items
    if watch.rate_limit is not None:
        status, retry_after = 429, watch.rate_limit.retry_after
    elif status != 429:
        status = 200 if any(row.get("available") for row in results + watch.items) else 503
    context["retry_after"] = retry_after
    response = render_markets(request, context, status)
    if retry_after is not None:
        response.headers["Retry-After"] = str(retry_after)
    return response
