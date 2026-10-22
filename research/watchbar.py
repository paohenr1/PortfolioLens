"""Daily yields, aligned reference FX and venue-specific Bitcoin statistics."""

import logging
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, localcontext

from market_data.errors import ProviderError, ProviderRateLimited
from market_data.public_markets import PublicMarketClient
from research.services import _reserve_request

logger = logging.getLogger("research")
LABELS = {
    "10y": "U.S. 10Y yield",
    "2y": "U.S. 2Y yield",
    "btc": "BTC / USD",
    "eur": "EUR / USD",
    "cad": "USD / CAD",
}


@dataclass
class WatchbarResult:
    items: list[dict]
    rate_limit: ProviderRateLimited | None = None


def empty_watchbar():
    return [{"key": key, "label": label} for key, label in LABELS.items()]


def formatted(value, places, *, signed=False):
    quantum = Decimal(1).scaleb(-places)
    rounded = value.quantize(quantum, rounding=ROUND_HALF_UP)
    return format(rounded, f"{'+' if signed else ''},.{places}f")


def change_fields(current, previous, *, yields=False):
    if previous is None:
        return {}
    delta = (current - previous) * 100 if yields else (current / previous - 1) * 100
    return {
        "change": formatted(delta, 1 if yields else 2, signed=True) + (" bps" if yields else "%"),
        "direction": "negative" if delta < 0 else "positive" if delta > 0 else "neutral",
    }


def daily_items(feed, kind):
    if not feed.observations:
        return []
    latest = feed.observations[-1]
    previous = feed.observations[-2] if len(feed.observations) > 1 else None
    output = []
    for key in ("10y", "2y") if kind == "treasury" else ("eur", "cad"):

        def value(row, key=key):
            if row is None:
                return None
            if kind == "treasury":
                return row.values[key]
            usd, eur = row.values["usd_cad"], row.values["eur_cad"]
            if key == "cad":
                return usd
            return eur / usd if usd is not None and eur is not None else None

        current, baseline = value(latest), value(previous)
        if current is None:
            output.append(
                {"key": key, "label": LABELS[key], "issue": "No value on the latest supplied date."}
            )
            continue
        source = "U.S. Treasury" if kind == "treasury" else "Bank of Canada"
        note = (
            "Daily Treasury curve"
            if kind == "treasury"
            else (
                "Derived daily reference rate: EUR/CAD ÷ USD/CAD"
                if key == "eur"
                else "Daily reference rate: Canadian dollars per U.S. dollar"
            )
        )
        output.append(
            {
                "key": key,
                "label": LABELS[key],
                "available": True,
                "value": formatted(current, 2 if kind == "treasury" else 4)
                + ("%" if kind == "treasury" else ""),
                "source": source,
                "as_of": latest.date,
                "retrieved_at": feed.retrieved_at,
                "note": note,
                "previous_date": previous.date if baseline is not None else None,
                **change_fields(current, baseline, yields=kind == "treasury"),
            }
        )
    return output


def bitcoin_item(data):
    return {
        "key": "btc",
        "label": LABELS["btc"],
        "available": True,
        "value": "$" + formatted(data.last, 2),
        "source": "Coinbase Exchange",
        "retrieved_at": data.retrieved_at,
        "note": "Coinbase BTC-USD 24-hour statistics. Change compares last price with "
        "the statistics window's opening price. Quote timestamp is not supplied; "
        "retrieval time does not establish freshness or a consolidated market price.",
        "change_basis": "24h statistics",
        **change_fields(data.last, data.opening),
    }


def load_watchbar(client_address, *, stop_error=None):
    items = {row["key"]: row for row in empty_watchbar()}
    limit = stop_error if isinstance(stop_error, ProviderRateLimited) else None
    with PublicMarketClient(before_request=lambda: _reserve_request(client_address)) as client:
        for source, keys in (
            ("treasury", ("10y", "2y")),
            ("forex", ("eur", "cad")),
            ("bitcoin", ("btc",)),
        ):
            try:
                if limit is not None:
                    raise limit
                data = getattr(client, source)()
                with localcontext() as context:
                    context.prec = 40
                    rows = (
                        [bitcoin_item(data)] if source == "bitcoin" else daily_items(data, source)
                    )
                for row in rows:
                    items[row["key"]] = row
                for key in keys:
                    if not items[key].get("available") and not items[key].get("issue"):
                        items[key]["issue"] = "No observations were supplied."
            except ProviderError as error:
                for key in keys:
                    items[key]["issue"] = error.message
                if isinstance(error, ProviderRateLimited):
                    limit = error
            except Exception:
                logger.exception("Unexpected public watchbar source failure")
                for key in keys:
                    items[key]["issue"] = "This market source is temporarily unavailable."
    return WatchbarResult(list(items.values()), limit)
