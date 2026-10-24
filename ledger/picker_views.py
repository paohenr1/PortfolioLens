"""Private, bounded instrument selection; never records or prices a transaction."""

import logging
from datetime import date

from django import forms
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from ledger import analytics, services
from ledger.domain import LedgerRuleError
from ledger.forms import ledger_today
from market_data.errors import InstrumentNotFound, ProviderError
from market_data.fields import valid_provider_id
from portfolios.services import PortfolioStorageUnavailable
from research import services as market_data
from research.forms import SearchForm

MAX_PICKER_RESULTS = 20
logger = logging.getLogger("research")


def _private_portfolio(request, portfolio_id):
    try:
        services.private_portfolio(request.user, portfolio_id)
    except PortfolioStorageUnavailable:
        return JsonResponse({"error": "Portfolio storage is unavailable."}, status=503)
    except services.PortfolioUnavailable:
        return JsonResponse({"error": "Portfolio not found."}, status=404)
    return None


def _listing(instrument):
    return {
        "id": instrument.id,
        "ticker": instrument.ticker,
        "name": instrument.name or instrument.ticker,
        "exchange": instrument.exchange_mic,
        "currency": instrument.currency,
    }


@never_cache
@login_required
@require_POST
def instrument_search(request, portfolio_id):
    denied = _private_portfolio(request, portfolio_id)
    if denied is not None:
        return denied
    form = SearchForm(request.POST)
    if not form.is_valid():
        return JsonResponse(
            {"error": "Enter a ticker or company name (up to 100 characters)."}, status=400
        )
    try:
        result = market_data.search_securities(
            form.cleaned_data["q"], request.META.get("REMOTE_ADDR", "unknown")
        )
    except InstrumentNotFound:
        return JsonResponse({"error": ProviderError.message}, status=503)
    except ProviderError as error:
        response = JsonResponse(
            {"error": error.message, "retry_after": error.retry_after}, status=error.status
        )
        if error.retry_after is not None:
            response.headers["Retry-After"] = str(error.retry_after)
        return response
    except Exception:
        logger.error("Unexpected trade instrument-search failure")
        return JsonResponse({"error": ProviderError.message}, status=503)
    results = [
        _listing(item)
        for item in result.securities
        if valid_provider_id(item.id)
        and item.ticker
        and item.currency == "USD"
        and item.exchange_mic in services.SUPPORTED_MICS
    ][:MAX_PICKER_RESULTS]
    return JsonResponse({"results": results})


@never_cache
@login_required
@require_POST
def held_instruments(request, portfolio_id):
    denied = _private_portfolio(request, portfolio_id)
    if denied is not None:
        return denied
    try:
        as_of = forms.DateField().clean(request.POST.get("as_of"))
        if not date(1900, 1, 1) <= as_of <= ledger_today():
            raise forms.ValidationError("Unsupported date.")
    except forms.ValidationError:
        return JsonResponse({"error": "Choose a transaction date through today."}, status=400)
    try:
        _, analysis, labels = analytics.positions_snapshot(request.user, portfolio_id, as_of=as_of)
    except PortfolioStorageUnavailable:
        return JsonResponse({"error": "Portfolio storage is unavailable."}, status=503)
    except services.PortfolioUnavailable:
        return JsonResponse({"error": "Portfolio not found."}, status=404)
    except LedgerRuleError:
        return JsonResponse(
            {"error": "Recorded holdings are unavailable. Review your transactions."}, status=503
        )
    results = [
        {
            "id": row.security_id,
            "ticker": labels[row.security_id].security_ticker,
            "name": labels[row.security_id].security_ticker,
            "exchange": labels[row.security_id].exchange_mic,
            "currency": "USD",
            "quantity": str(row.quantity),
        }
        for row in analysis.positions[:MAX_PICKER_RESULTS]
    ]
    return JsonResponse(
        {
            "results": results,
            "as_of": as_of.isoformat(),
            "cash": str(analysis.cash),
            "truncated": len(analysis.positions) > MAX_PICKER_RESULTS,
        }
    )
