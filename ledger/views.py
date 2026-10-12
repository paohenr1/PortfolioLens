"""Ledger forms/history are private; no transaction execution is performed."""

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods

from ledger import analytics, services
from ledger.allocations import allocation_weights
from ledger.domain import LedgerRuleError
from ledger.fifo import analyze
from ledger.forms import EntryForm
from ledger.valuation_forms import ValuationForm
from ledger.valuation_services import ValuationLimitError, load_valuation
from market_data.errors import ProviderError
from portfolios.services import PortfolioStorageUnavailable


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def valuation(request, portfolio_id):
    try:
        portfolio = services.private_portfolio(request.user, portfolio_id)
    except (PortfolioStorageUnavailable, services.PortfolioUnavailable) as error:
        return private_error(request, error)
    form = ValuationForm(request.POST if request.method == "POST" else None)
    context = {"portfolio": portfolio, "form": form}
    status, provider_error = 200, None
    if request.method == "POST":
        if not form.is_valid():
            status = 400
        else:
            try:
                # Materialize once before I/O; a later append cannot mix new cash
                # or split quantities into this response's earlier quote snapshot.
                portfolio, analysis, labels = analytics.positions_snapshot(
                    request.user, portfolio_id, as_of=form.cleaned_data["as_of"]
                )
                result, provider_error = load_valuation(
                    analysis,
                    labels,
                    form.cleaned_data["as_of"],
                    request.META.get("REMOTE_ADDR", "unknown"),
                )
            except (PortfolioStorageUnavailable, services.PortfolioUnavailable) as error:
                return private_error(request, error)
            except LedgerRuleError:
                return render(request, "ledger/calculations_unavailable.html", status=503)
            except ValuationLimitError as error:
                form.add_error(None, str(error))
                status = 400
            else:
                allocation = allocation_weights(result)
                context.update(
                    valuation=result,
                    allocation=allocation,
                    allocation_rows=[
                        {"component": row, "instrument": labels.get(row.security_id)}
                        for row in allocation.rows
                    ],
                    rows=[
                        {"value": row, "instrument": labels[row.position.security_id]}
                        for row in result.rows
                    ],
                )
                if provider_error:
                    status = 429 if provider_error.status == 429 else 503
    response = render(request, "ledger/valuation.html", context, status=status)
    if provider_error and provider_error.retry_after:
        response.headers["Retry-After"] = str(provider_error.retry_after)
    return response


@never_cache
@login_required
@require_GET
def positions(request, portfolio_id):
    try:
        portfolio, result, labels = analytics.positions_snapshot(request.user, portfolio_id)
    except (PortfolioStorageUnavailable, services.PortfolioUnavailable) as error:
        return private_error(request, error)
    except LedgerRuleError:
        return render(request, "ledger/calculations_unavailable.html", status=503)
    position_rows = [
        {"position": item, "instrument": labels[item.security_id]} for item in result.positions
    ]
    sale_rows = [{"sale": item, "instrument": labels[item.security_id]} for item in result.sales]
    return render(
        request,
        "ledger/positions.html",
        {
            "portfolio": portfolio,
            "analysis": result,
            "positions": Paginator(position_rows, 25).get_page(request.GET.get("positions_page")),
            "sales": Paginator(sale_rows, 25).get_page(request.GET.get("sales_page")),
        },
    )


def private_error(request, error):
    if isinstance(error, PortfolioStorageUnavailable):
        return render(request, "portfolios/unavailable.html", status=503)
    return render(request, "portfolios/not_found.html", status=404)


@never_cache
@login_required
@require_GET
def history(request, portfolio_id):
    try:
        portfolio, entries = analytics.journal_snapshot(request.user, portfolio_id)
        # FIFO validates exact per-lot split quantities, including historical events.
        projection = analyze([entry.as_input() for entry in entries])
    except (PortfolioStorageUnavailable, services.PortfolioUnavailable) as error:
        return private_error(request, error)
    except LedgerRuleError:
        return render(request, "ledger/calculations_unavailable.html", status=503)
    page = Paginator(entries, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "ledger/history.html",
        {"portfolio": portfolio, "page": page, "cash": projection.cash},
    )


@never_cache
@login_required
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def entry_create(request, portfolio_id):
    try:
        portfolio = services.private_portfolio(request.user, portfolio_id)
    except (PortfolioStorageUnavailable, services.PortfolioUnavailable) as error:
        return private_error(request, error)
    form = EntryForm(request.POST if request.method == "POST" else None)
    context = {"portfolio": portfolio, "form": form}
    status = 200
    retry_after = None
    if request.method == "POST" and form.is_valid():
        try:
            services.append_entry(
                user=request.user,
                portfolio_id=portfolio.pk,
                client_key=form.cleaned_data["client_key"],
                intent=form.intent,
                client_address=request.META.get("REMOTE_ADDR", "unknown"),
            )
        except (PortfolioStorageUnavailable, services.PortfolioUnavailable) as error:
            return private_error(request, error)
        except ValidationError as error:
            for field, errors in error.message_dict.items():
                form.add_error(None if field == "__all__" else field, errors)
        except ProviderError as error:
            context["provider_error"] = error
            status, retry_after = error.status, error.retry_after
        else:
            return redirect("ledger_history", portfolio_id=portfolio.pk)
    response = render(request, "ledger/create.html", context, status=status)
    if retry_after:
        response.headers["Retry-After"] = str(retry_after)
    return response
