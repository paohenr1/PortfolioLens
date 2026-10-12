"""Synthetic drill data; never allow this helper to use the development database."""

import hashlib
import json
import os
import re
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"


def snapshot():
    from django.apps import apps
    from django.db.migrations.recorder import MigrationRecorder

    result = {}
    for model in (*apps.get_models(include_auto_created=True), MigrationRecorder.Migration):
        rows = list(model.objects.order_by(model._meta.pk.name).values())
        encoded = json.dumps(rows, default=str, sort_keys=True).encode()
        result[model._meta.label] = {
            "rows": len(rows),
            "digest": hashlib.sha256(encoded).hexdigest(),
        }
    return result


def seed():
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group, Permission
    from django.test import Client

    from ledger.corrections import commit_correction, preview_correction
    from ledger.services import append_entry
    from operations.rate_limits import reserve
    from portfolios.services import create_portfolio
    from tests.test_actions import dividend, split
    from tests.test_ledger import REFERENCE
    from tests.test_ledger_domain import cash, trade
    from watchlists.services import add_instrument, create_watchlist

    owner = get_user_model().objects.create_user(
        "backup-owner", password="Synthetic-backup-pass-94"
    )
    other = get_user_model().objects.create_user("backup-other", password="Synthetic-other-pass-94")
    group = Group.objects.create(name="Synthetic backup readers")
    group.permissions.add(Permission.objects.get(codename="view_portfolio"))
    owner.groups.add(group)
    owner.user_permissions.add(Permission.objects.get(codename="view_watchlist"))
    portfolio = create_portfolio(owner=owner, name="Backup owner portfolio")
    create_portfolio(owner=other, name="Backup other portfolio")
    with patch("research.services.security_details", return_value=REFERENCE):
        entries = []
        for intent in (
            cash(),
            trade(price="10"),
            cash("FEE", "2", 3),
            dividend(sequence=4),
            split(sequence=5),
            trade("SELL", "4", "8", "1", 6),
        ):
            entries.append(
                append_entry(
                    user=owner,
                    portfolio_id=portfolio.pk,
                    client_key=uuid.uuid4(),
                    intent=intent,
                    client_address="synthetic-backup-client",
                )
            )
        replacement = cash("FEE", "3", 3)
        preview = preview_correction(
            user=owner,
            portfolio_id=portfolio.pk,
            target_id=entries[2].pk,
            intent=replacement,
            reason="Synthetic backup correction",
        )
        commit_correction(
            user=owner,
            portfolio_id=portfolio.pk,
            target_id=entries[2].pk,
            intent=replacement,
            reason="Synthetic backup correction",
            client_key=uuid.uuid4(),
            expected_version=preview[4],
            client_address="synthetic-backup-client",
        )
        for user in (owner, other):
            watchlist = create_watchlist(user=user, name="Backup watchlist")
            watchlist.price_basis, watchlist.volume_basis, watchlist.instrument_order = (
                "adjusted",
                "raw",
                "ticker",
            )
            watchlist.save(update_fields=("price_basis", "volume_basis", "instrument_order"))
            add_instrument(
                user=user,
                watchlist_id=watchlist.pk,
                security_id="sec_fixture_primary",
                client_address="synthetic-backup-client",
            )
            Client().force_login(user)
    assert reserve("market", "synthetic-backup-client") is None
    assert reserve("auth", "synthetic-backup-client") is None


def verify():
    from decimal import Decimal

    from django.contrib.auth import get_user_model
    from django.contrib.sessions.models import Session
    from django.db import IntegrityError, transaction
    from django.test import Client

    from ledger.analytics import positions_snapshot
    from ledger.models import Correction, Entry
    from portfolios.models import Portfolio
    from watchlists.models import Watchlist

    owner = get_user_model().objects.get(username="backup-owner")
    other = get_user_model().objects.get(username="backup-other")
    assert owner.check_password("Synthetic-backup-pass-94")
    assert owner.has_perm("portfolios.view_portfolio")
    assert owner.has_perm("watchlists.view_watchlist")
    sessions = [session.get_decoded() for session in Session.objects.all()]
    assert {session["_auth_user_id"] for session in sessions} == {str(owner.pk), str(other.pk)}
    assert all(
        session["_auth_user_hash"]
        == (owner if session["_auth_user_id"] == str(owner.pk) else other).get_session_auth_hash()
        for session in sessions
    )
    portfolio = Portfolio.objects.get(owner=owner)
    _, holdings, _ = positions_snapshot(owner, portfolio.pk)
    assert holdings.cash == Decimal("932.00")
    assert holdings.open_cost_basis == Decimal("80.80")
    assert holdings.realized_gain == Decimal("10.80")
    assert holdings.positions[0].quantity == Decimal("16")
    assert Correction.objects.count() == 1 and Entry.objects.count() == 7
    audit = Correction.objects.get()
    assert audit.target.amount == Decimal("2") and audit.replacement.amount == Decimal("3")
    # A successful restore must recreate database immutability, not just row values.
    try:
        with transaction.atomic():
            Entry.objects.filter(pk=audit.target.pk).update(amount=Decimal("999"))
    except IntegrityError:
        pass
    else:
        raise AssertionError("Restored journal immutability was lost.")
    watchlist = Watchlist.objects.get(owner=owner)
    assert (watchlist.price_basis, watchlist.volume_basis, watchlist.instrument_order) == (
        "adjusted",
        "raw",
        "ticker",
    )
    client = Client(HTTP_HOST="127.0.0.1")
    client.force_login(other)
    for route in (f"/portfolios/{portfolio.pk}/", f"/watchlists/{watchlist.pk}/"):
        response = client.get(route)
        assert response.status_code == 404
        assert "no-store" in response.headers["Cache-Control"]


def main():
    import django

    django.setup()
    from django.conf import settings

    configured = settings.DATABASES["default"]
    if (
        not re.fullmatch(r"test_stock_backup_[0-9a-f]{32}_[ab]", configured["NAME"])
        or configured["USER"] != "stock_research_test"
    ):
        raise SystemExit("Backup fixtures require an owned disposable test-role database.")
    stage, manifest = sys.argv[1], Path(sys.argv[2])
    if stage == "seed":
        seed()
        manifest.write_text(json.dumps(snapshot(), sort_keys=True))
        manifest.chmod(0o600)
    elif stage == "verify":
        assert snapshot() == json.loads(manifest.read_text()), "Restored row digests differ."
        verify()
    else:
        raise SystemExit("Unsupported backup fixture stage.")
    print(f"Synthetic backup {stage} PASS; provider transport disabled.")


if __name__ == "__main__":
    main()
