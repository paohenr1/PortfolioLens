"""Owner-serialized atomic saves and deletion; no provider I/O inside locks."""

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404
from django.utils import timezone

from portfolios import snapshot_previews as previews
from portfolios.models import HoldingsSnapshot, SnapshotHolding, SnapshotSubmission
from portfolios.services import require_portfolio_storage

MAX_SNAPSHOTS = 50


def owned_snapshots(user):
    previews.active_user(user)
    require_portfolio_storage()
    return HoldingsSnapshot.objects.filter(owner=user, owner__is_active=True)


def private_snapshot(user, snapshot_id):
    snapshot = owned_snapshots(user).filter(pk=snapshot_id).first()
    if snapshot is None:
        raise Http404
    return snapshot


def lock_owner(user):
    if not user.__class__.objects.select_for_update().filter(pk=user.pk, is_active=True).exists():
        raise PermissionDenied
    SnapshotSubmission.objects.filter(
        owner=user, snapshot__isnull=True, expires_at__lte=timezone.now()
    ).delete()


def input_digest(payload):
    # Ignore candidate lists/retrieval times: retry identity describes the selected inputs.
    content = {key: payload[key] for key in ("name", "as_of", "cash")}
    content["rows"] = sorted(
        [
            {key: row[key] for key in ("ticker", "exchange_mic", "quantity", "currency")}
            | {"security_id": row["reference"]["security_id"]}
            for row in payload["rows"]
        ],
        key=lambda row: row["security_id"],
    )

    content["cash"] = format(Decimal(content["cash"]), ".2f")
    for row in content["rows"]:
        row["quantity"] = format(Decimal(row["quantity"]), ".6f")
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def save_snapshot(*, user, token, confirmed):
    owned_snapshots(user)
    payload = previews.decode(token, user, stage="verified")
    if confirmed is not True:
        raise ValidationError("Confirm the date, cash and raw share basis before saving.")
    digest = input_digest(payload)
    with transaction.atomic():
        lock_owner(user)
        # Lock waits can cross the expiry boundary: validate again inside the transaction.
        previews.validate(payload, user, stage="verified")
        receipt = SnapshotSubmission.objects.filter(owner=user, key=payload["key"]).first()
        if receipt:
            if receipt.digest != digest:
                raise ValidationError("This submission key was already used with different inputs.")
            if receipt.snapshot_id is None:
                raise ValidationError("This snapshot was deleted. Start a new import.")
            return private_snapshot(user, receipt.snapshot_id)
        if owned_snapshots(user).count() >= MAX_SNAPSHOTS:
            raise ValidationError("An account can have up to 50 holdings snapshots.")
        snapshot = HoldingsSnapshot.objects.create(
            owner=user,
            name=payload["name"],
            as_of=payload["as_of"],
            cash=payload["cash"],
        )
        SnapshotHolding.objects.bulk_create(
            [
                SnapshotHolding(
                    snapshot=snapshot,
                    security_id=row["reference"]["security_id"],
                    ticker=row["ticker"],
                    exchange_mic=row["exchange_mic"],
                    quantity=row["quantity"],
                    currency=row["currency"],
                    name=row["reference"]["name"],
                    reference_retrieved_at=datetime.fromisoformat(row["reference"]["retrieved_at"]),
                )
                for row in payload["rows"]
            ]
        )
        SnapshotSubmission.objects.create(
            owner=user,
            key=payload["key"],
            digest=digest,
            snapshot=snapshot,
            expires_at=datetime.fromtimestamp(payload["issued"] + previews.LIFETIME, UTC),
        )
    return snapshot


def delete_snapshot(*, user, snapshot_id):
    private_snapshot(user, snapshot_id)
    with transaction.atomic():
        lock_owner(user)
        private_snapshot(user, snapshot_id).delete()
