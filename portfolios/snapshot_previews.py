"""Bounded signed workflow state, revalidated at every transition and save."""

import csv
import io
import time
import uuid
from datetime import datetime

from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils.timezone import is_aware

from market_data.fields import valid_provider_id
from portfolios.holdings_csv import HEADER, has_control, parse_holdings_csv
from portfolios.holdings_forms import HoldingsMetadataForm

SALT = "portfolios.holdings-snapshot.v1"
LIFETIME = 15 * 60
MAX_TOKEN = 128 * 1024
MAX_CHOICES = 5
INVALID = "This preview is invalid or expired. Check the CSV again to start a new import."
CONFIRMATION = (
    "These quantities and the cash balance describe my holdings at the close of the "
    "selected date. Quantities include trades and splits effective by that date and "
    "match the raw share basis. This is a holdings snapshot, not transaction history."
)


def active_user(user):
    if not user.is_authenticated or not user.is_active:
        raise PermissionDenied


def text_field(value, limit, *, empty=False):
    return (
        isinstance(value, str)
        and len(value) <= limit
        and (empty or bool(value.strip()))
        and not has_control(value)
    )


def reference_valid(reference, row):
    if not isinstance(reference, dict) or set(reference) != {
        "security_id",
        "ticker",
        "exchange_mic",
        "currency",
        "name",
        "retrieved_at",
    }:
        return False
    if not valid_provider_id(reference["security_id"]):
        return False
    if any(reference[key] != row[key] for key in ("ticker", "exchange_mic", "currency")):
        return False
    if not text_field(reference["name"], 512, empty=True):
        return False
    try:
        retrieved = datetime.fromisoformat(reference["retrieved_at"])
        return is_aware(retrieved) and retrieved.timestamp() <= time.time() + 60
    except (ValueError, TypeError, OverflowError):
        return False


def require(condition):
    if not condition:
        raise ValueError()


def validate(payload, user, *, stage=None):
    active_user(user)
    try:
        require(
            isinstance(payload, dict)
            and set(payload)
            == {"version", "owner", "key", "issued", "stage", "name", "as_of", "cash", "rows"}
        )
        require(type(payload["version"]) is int and payload["version"] == 1)
        require(payload["owner"] == str(user.pk))
        require(type(payload["issued"]) is int and 0 <= time.time() - payload["issued"] < LIFETIME)
        require(str(uuid.UUID(payload["key"])) == payload["key"])
        require(payload["stage"] in ("input", "matches", "verified"))
        require(stage is None or payload["stage"] == stage)
        require(all(isinstance(payload[key], str) for key in ("name", "as_of", "cash")))
        form = HoldingsMetadataForm({key: payload[key] for key in ("name", "as_of", "cash")})
        require(form.is_valid())
        require(payload["name"] == form.cleaned_data["name"])
        require(payload["as_of"] == form.cleaned_data["as_of"].isoformat())
        require(payload["cash"] == format(form.cleaned_data["cash"], "f"))
        rows = payload["rows"]
        require(isinstance(rows, list) and len(rows) <= 5)
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(HEADER)
        selected_ids = set()
        for row in rows:
            require(isinstance(row, dict) and set(row) == {*HEADER, "choices", "reference"})
            require(all(isinstance(row[key], str) for key in HEADER))
            writer.writerow([row[key] for key in HEADER])
            choices = row["choices"]
            require(isinstance(choices, list) and len(choices) <= MAX_CHOICES)
            require(all(reference_valid(choice, row) for choice in choices))
            require(len({choice["security_id"] for choice in choices}) == len(choices))
            reference = row["reference"]
            if payload["stage"] == "input":
                require(not choices and reference is None)
            elif payload["stage"] == "matches":
                require(reference is None)
            else:
                require(reference_valid(reference, row))
                require(reference["security_id"] in {choice["security_id"] for choice in choices})
                require(reference["security_id"] not in selected_ids)
                selected_ids.add(reference["security_id"])
        parsed = parse_holdings_csv(io.BytesIO(output.getvalue().encode()))
        require(not parsed.issues and len(parsed.holdings) == len(rows))
        for row, holding in zip(rows, parsed.holdings, strict=True):
            require(row["ticker"] == holding.ticker)
            require(row["exchange_mic"] == holding.exchange_mic)
            require(row["currency"] == holding.currency)
            require(row["quantity"] == format(holding.quantity, "f"))
        require(rows or form.cleaned_data["cash"] > 0)
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ValidationError(INVALID) from None
    return payload


def start(data, user):
    active_user(user)
    return {
        "version": 1,
        "owner": str(user.pk),
        "key": str(uuid.uuid4()),
        "issued": int(time.time()),
        "stage": "input",
        "name": data["name"],
        "as_of": data["as_of"].isoformat(),
        "cash": format(data["cash"], "f"),
        "rows": [
            {
                "ticker": row.ticker,
                "exchange_mic": row.exchange_mic,
                "quantity": format(row.quantity, "f"),
                "currency": row.currency,
                "choices": [],
                "reference": None,
            }
            for row in data["holdings_file"]
        ],
    }


def encode(payload, user):
    validate(payload, user)
    token = signing.dumps(payload, salt=SALT, compress=False)
    if len(token) > MAX_TOKEN:
        raise ValidationError(INVALID)
    return token


def decode(token, user, *, stage=None):
    active_user(user)
    try:
        if not isinstance(token, str) or len(token) > MAX_TOKEN or token.startswith("."):
            raise signing.BadSignature()
        payload = signing.loads(token, salt=SALT, max_age=LIFETIME)
    except (signing.BadSignature, ValueError, TypeError):
        raise ValidationError(INVALID) from None
    return validate(payload, user, stage=stage)
