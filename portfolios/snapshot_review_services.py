"""Private consistent snapshot reads and at most five explicit daily-price requests."""

import logging
from dataclasses import dataclass

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from market_data.errors import ProviderError, ProviderRateLimited
from portfolios.holdings_forms import HoldingsMetadataForm
from portfolios.models import HoldingsSnapshot
from portfolios.snapshot_review import ReviewHolding, review_snapshot, validate_inputs
from portfolios.snapshot_services import owned_snapshots, private_snapshot
from research import services as market_data

logger = logging.getLogger("research")


@dataclass(frozen=True)
class ReviewInputs:
    snapshot: HoldingsSnapshot
    holdings: tuple[ReviewHolding, ...]


def snapshot_inputs(user, snapshot_id):
    owned_snapshots(user)
    with transaction.atomic():
        # Deletion also locks this owner. Copy parent and children consistently, then
        # release the lock before any provider I/O. This read does not clean receipts.
        if (
            not user.__class__.objects.select_for_update()
            .filter(pk=user.pk, is_active=True)
            .exists()
        ):
            raise PermissionDenied
        snapshot = private_snapshot(user, snapshot_id)
        rows = tuple(snapshot.holdings.all()[:6])
        holdings = tuple(
            ReviewHolding(row.security_id, row.ticker, row.exchange_mic, row.quantity)
            for row in rows
        )
        form = HoldingsMetadataForm(
            {
                "name": snapshot.name,
                "as_of": snapshot.as_of.isoformat(),
                "cash": format(snapshot.cash, "f"),
            }
        )
        if (
            not form.is_valid()
            or snapshot.currency != "USD"
            or snapshot.confirmation_version != 1
            or any(row.currency != "USD" for row in rows)
        ):
            raise ValidationError("Saved snapshot inputs could not be validated for review.")
        try:
            validate_inputs(snapshot.as_of, snapshot.cash, holdings)
        except ValueError:
            raise ValidationError(
                "Saved snapshot inputs could not be validated for review."
            ) from None
    return ReviewInputs(snapshot, holdings)


def load_review(user, snapshot_id, client_address):
    inputs = snapshot_inputs(user, snapshot_id)
    histories, issues, error = {}, {}, None
    for holding in inputs.holdings:
        if isinstance(error, ProviderRateLimited):
            issues[holding.security_id] = "Not requested: the shared market-data limit was reached."
            continue
        try:
            histories[holding.security_id] = market_data.daily_prices(
                holding.security_id, inputs.snapshot.as_of, client_address
            )
        except ProviderError as failure:
            issues[holding.security_id] = failure.message
            if error is None or isinstance(failure, ProviderRateLimited):
                error = failure
        except Exception:
            logger.error("Unexpected snapshot review price failure")
            issues[holding.security_id] = ProviderError.message
            error = error or ProviderError()
    # Do not show a result for a snapshot deleted or account disabled during I/O.
    private_snapshot(user, snapshot_id)
    return (
        inputs,
        review_snapshot(
            inputs.snapshot.as_of,
            inputs.snapshot.cash,
            inputs.holdings,
            histories,
            issues=issues,
        ),
        error,
    )
