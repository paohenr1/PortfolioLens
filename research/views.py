import logging
from datetime import UTC, datetime, timedelta

from django.http import Http404
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_safe

from market_data.errors import InstrumentNotFound, ProviderError
from market_data.intrinio import valid_security_id
from research import services
from research.charts import build_price_chart
from research.forms import PriceHistoryForm, SearchForm, StatementForm
from research.fundamentals import statement_presentation
from research.stock_risk import calculate_stock_risk
from research.stock_risk_chart import stock_drawdown_chart
from research.volume_charts import build_volume_chart

logger = logging.getLogger("research")


@require_safe
def home(request):
    from research.market_views import render_markets

    return render_markets(request)


def _error_page(request, template, context, error):
    response = render(request, template, {**context, "provider_error": error}, status=error.status)
    response.headers["Cache-Control"] = "no-store"
    if error.retry_after is not None:
        response.headers["Retry-After"] = str(error.retry_after)
    return response


@require_GET
def search(request):
    form = SearchForm(request.GET if "q" in request.GET else None)
    context = {"form": form}
    if not form.is_bound:
        return render(request, "research/search.html", context)
    if not form.is_valid():
        return render(request, "research/search.html", context, status=400)
    try:
        result = services.search_securities(
            form.cleaned_data["q"], request.META.get("REMOTE_ADDR", "")
        )
    except InstrumentNotFound:
        # A search endpoint's 404 is not proof that a user's ticker does not exist.
        return _error_page(request, "research/search.html", context, ProviderError())
    except ProviderError as error:
        return _error_page(request, "research/search.html", context, error)
    except Exception:
        # Catch only at this public boundary; preserve a redacted diagnostic trace.
        logger.exception("Unexpected stock-search failure")
        return _error_page(request, "research/search.html", context, ProviderError())
    response = render(request, "research/search.html", {**context, "result": result})
    response.headers["Cache-Control"] = "no-store"
    return response


@require_GET
def security(request, security_id):
    if not valid_security_id(security_id):
        raise Http404("Invalid instrument identifier.")
    try:
        result = services.security_details(security_id, request.META.get("REMOTE_ADDR", ""))
    except ProviderError as error:
        return _error_page(request, "research/security.html", {}, error)
    except Exception:
        logger.exception("Unexpected security-reference failure")
        return _error_page(request, "research/security.html", {}, ProviderError())
    response = render(
        request,
        "research/security.html",
        {"security": result.security, "retrieved_at": result.retrieved_at},
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@require_GET
def prices(request, security_id):
    if not valid_security_id(security_id):
        raise Http404("Invalid instrument identifier.")
    today = datetime.now(UTC).date()
    submitted = any(
        field in request.GET for field in ("start_date", "end_date", "basis", "volume_basis")
    )
    form = PriceHistoryForm(
        request.GET if submitted else None,
        # Leave the current UTC day outside the default risk window. The user
        # can still request it for the supplied-price chart without risk metrics.
        initial={
            "start_date": today - timedelta(days=90),
            "end_date": today - timedelta(days=1),
            "basis": "adjusted",
            "volume_basis": "raw",
        },
    )
    context = {"form": form, "security_id": security_id}
    status = 200
    if submitted:
        if not form.is_valid():
            status = 400
        else:
            try:
                history = services.historical_prices(
                    security_id,
                    form.cleaned_data["start_date"],
                    form.cleaned_data["end_date"],
                    request.META.get("REMOTE_ADDR", ""),
                )
                # Reuse this bounded response; risk never triggers another lookup.
                risk = calculate_stock_risk(history, form.cleaned_data["basis"])
                context.update(
                    history=history,
                    chart=build_price_chart(history, form.cleaned_data["basis"]),
                    basis=form.cleaned_data["basis"],
                    stock_risk=risk,
                    stock_drawdown_chart=stock_drawdown_chart(risk),
                    volume_chart=build_volume_chart(history, form.cleaned_data["volume_basis"]),
                    volume_basis=form.cleaned_data["volume_basis"],
                    latest_observation_date=(
                        history.observations[-1].date if history.observations else None
                    ),
                )
            except ProviderError as error:
                return _error_page(request, "research/prices.html", context, error)
            except Exception:
                logger.exception("Unexpected historical-price failure")
                return _error_page(request, "research/prices.html", context, ProviderError())
    response = render(request, "research/prices.html", context, status=status)
    response.headers["Cache-Control"] = "no-store"
    return response


@require_GET
def financials(request, security_id):
    if not valid_security_id(security_id):
        raise Http404("Invalid instrument identifier.")
    submitted = any(
        field in request.GET for field in ("statement_code", "fiscal_year", "fiscal_period")
    )
    form = StatementForm(
        request.GET if submitted else None,
        initial={
            "statement_code": "income_statement",
            "fiscal_year": datetime.now(UTC).year - 1,
            "fiscal_period": "FY",
        },
    )
    context = {"form": form, "security_id": security_id}
    status = 200
    if submitted:
        if not form.is_valid():
            status = 400
        else:
            try:
                statement = services.company_statement(
                    security_id,
                    form.cleaned_data["statement_code"],
                    form.cleaned_data["fiscal_year"],
                    form.cleaned_data["fiscal_period"],
                    request.META.get("REMOTE_ADDR", ""),
                )
                context.update(statement=statement, **statement_presentation(statement))
            except ProviderError as error:
                return _error_page(request, "research/financials.html", context, error)
            except Exception:
                logger.exception("Unexpected company-statement failure")
                return _error_page(request, "research/financials.html", context, ProviderError())
    response = render(request, "research/financials.html", context, status=status)
    response.headers["Cache-Control"] = "no-store"
    return response
