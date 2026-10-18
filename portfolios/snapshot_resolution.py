"""Explicit bounded reference lookups through the existing shared request budget."""

import copy
import logging
from datetime import datetime

from django.core.exceptions import ValidationError

from market_data.errors import InvalidResponse, ProviderError
from market_data.fields import valid_provider_id
from portfolios import snapshot_previews as previews
from research import services as market_data

logger = logging.getLogger("research")


def reference(security, retrieved_at, row):
    if not isinstance(retrieved_at, datetime):
        raise InvalidResponse()
    result = {
        "security_id": security.id,
        "ticker": security.ticker,
        "exchange_mic": security.exchange_mic,
        "currency": security.currency,
        "name": security.name or "",
        "retrieved_at": retrieved_at.isoformat(),
    }
    if not previews.reference_valid(result, row):
        raise InvalidResponse()
    return result


def find_matches(payload, user, address):
    previews.validate(payload, user)
    if payload["stage"] not in ("input", "matches"):
        raise ValidationError(previews.INVALID)
    payload = copy.deepcopy(payload)
    payload["stage"] = "matches"
    issues, provider_error = [], None
    for index, row in enumerate(payload["rows"], 1):
        if row["choices"]:
            continue
        try:
            result = market_data.search_securities(row["ticker"], address)
            if result.pagination_complete is not True:
                issues.append(f"Holding {index}: search is incomplete; no match can be confirmed.")
                continue
            if len(result.securities) > 20:
                raise InvalidResponse()
            choices = [
                reference(security, result.retrieved_at, row)
                for security in result.securities
                if security.ticker == row["ticker"]
                and security.exchange_mic == row["exchange_mic"]
                and security.currency == "USD"
            ]
            if len(choices) > previews.MAX_CHOICES:
                issues.append(
                    f"Holding {index}: too many exact matches; import remains unresolved."
                )
            elif not choices:
                issues.append(f"Holding {index}: no exact ticker/MIC/USD match was returned.")
            elif len({choice["security_id"] for choice in choices}) != len(choices):
                raise InvalidResponse()
            else:
                row["choices"] = choices
        except ProviderError as error:
            provider_error = error
            break
        except Exception:
            logger.error("Unexpected snapshot instrument-search failure")
            provider_error = ProviderError()
            break
    return payload, issues, provider_error


def validate_selections(payload, selections, user, address):
    previews.validate(payload, user, stage="matches")
    if len(selections) != len(payload["rows"]):
        raise ValidationError("Select one instrument for every holding.")
    for row, selected in zip(payload["rows"], selections, strict=True):
        if not valid_provider_id(selected) or selected not in {
            choice["security_id"] for choice in row["choices"]
        }:
            raise ValidationError("Select one of the displayed matches for every holding.")
    if len(set(selections)) != len(selections):
        raise ValidationError("Two holdings resolve to the same instrument. Correct the CSV.")
    verified = copy.deepcopy(payload)
    try:
        for row, selected in zip(verified["rows"], selections, strict=True):
            result = market_data.security_details(selected, address)
            if result.security.id != selected:
                raise InvalidResponse()
            row["reference"] = reference(result.security, result.retrieved_at, row)
    except ProviderError:
        raise
    except Exception:
        logger.error("Unexpected snapshot instrument-verification failure")
        raise ProviderError() from None
    verified["stage"] = "verified"
    return previews.validate(verified, user, stage="verified")
