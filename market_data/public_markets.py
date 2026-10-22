"""Bounded public-source transport and normalization; no credentials or proxy substitutions."""

import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from xml.etree import ElementTree

import httpx

from market_data.errors import ProviderError, ProviderRateLimited
from market_data.intrinio import _retry_after

MAX_PUBLIC_BYTES = 2 * 1024 * 1024
TREASURY_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
)
FX_URL = "https://www.bankofcanada.ca/valet/observations/FXUSDCAD,FXEURCAD/json"
BTC_URL = "https://api.exchange.coinbase.com/products/BTC-USD/stats"
ATOM = "{http://www.w3.org/2005/Atom}"
DATA = "{http://schemas.microsoft.com/ado/2007/08/dataservices}"
METADATA = "{http://schemas.microsoft.com/ado/2007/08/dataservices/metadata}"


class PublicFeedUnavailable(ProviderError):
    code = "public_feed_unavailable"
    message = "This market source is temporarily unavailable."


class PublicFeedInvalid(PublicFeedUnavailable):
    code = "public_feed_invalid"
    message = "This market source returned data that could not be validated."


@dataclass(frozen=True)
class DailyObservation:
    date: date
    values: dict[str, Decimal | None]


@dataclass(frozen=True)
class DailyFeed:
    observations: tuple[DailyObservation, ...]
    retrieved_at: datetime


@dataclass(frozen=True)
class BitcoinStatistics:
    last: Decimal
    opening: Decimal
    retrieved_at: datetime


def number(value, *, allow_negative=False):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise PublicFeedInvalid()
    if isinstance(value, str) and not re.fullmatch(r"-?\d{1,15}(?:\.\d{1,12})?", value):
        raise PublicFeedInvalid()
    try:
        result = Decimal(value)
    except (ValueError, ArithmeticError):
        raise PublicFeedInvalid() from None
    if not result.is_finite() or not -Decimal("1e12") <= result <= Decimal("1e12"):
        raise PublicFeedInvalid()
    if not allow_negative and result <= 0:
        raise PublicFeedInvalid()
    if result and abs(result) < Decimal("0.000000000001"):
        raise PublicFeedInvalid()
    return result


def observation_date(value, today):
    try:
        if not isinstance(value, str) or len(value) != 10:
            raise ValueError
        observed = date.fromisoformat(value)
    except ValueError:
        raise PublicFeedInvalid() from None
    if observed.isoformat() != value or observed > today:
        raise PublicFeedInvalid()
    return observed


def normalize_treasury(raw, *, today, year):
    try:
        text = raw.decode("utf-8")
    except UnicodeError:
        raise PublicFeedInvalid() from None
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise PublicFeedInvalid()
    try:
        root = ElementTree.fromstring(text)
    except (ElementTree.ParseError, ValueError):
        raise PublicFeedInvalid() from None
    if root.tag != ATOM + "feed":
        raise PublicFeedInvalid()
    entries = root.findall(ATOM + "entry")
    if len(entries) > 370:
        raise PublicFeedInvalid()
    observations = {}
    for entry in entries:
        fields = entry.find(ATOM + "content/" + METADATA + "properties")
        if fields is None:
            raise PublicFeedInvalid()
        raw_date = fields.findtext(DATA + "NEW_DATE")
        if not isinstance(raw_date, str) or not raw_date.endswith("T00:00:00"):
            raise PublicFeedInvalid()
        observed = observation_date(raw_date.removesuffix("T00:00:00"), today)
        if observed.year != year or observed in observations:
            raise PublicFeedInvalid()
        values = {}
        for key, tag in (("2y", "BC_2YEAR"), ("10y", "BC_10YEAR")):
            nodes = fields.findall(DATA + tag)
            if len(nodes) > 1:
                raise PublicFeedInvalid()
            value = None
            if nodes and nodes[0].get(METADATA + "null") != "true":
                value = number(nodes[0].text, allow_negative=True)
            if value is not None and not -10 <= value <= 100:
                raise PublicFeedInvalid()
            values[key] = value
        observations[observed] = DailyObservation(observed, values)
    return DailyFeed(tuple(observations[d] for d in sorted(observations)), datetime.now(UTC))


def normalize_fx(payload, *, today):
    if not isinstance(payload, dict):
        raise PublicFeedInvalid()
    details = payload.get("seriesDetail")
    if not isinstance(details, dict):
        raise PublicFeedInvalid()
    for series, label in (("FXUSDCAD", "USD/CAD"), ("FXEURCAD", "EUR/CAD")):
        if not isinstance(details.get(series), dict) or details[series].get("label") != label:
            raise PublicFeedInvalid()
    rows = payload.get("observations")
    if not isinstance(rows, list) or len(rows) > 5:
        raise PublicFeedInvalid()
    observations = {}
    for row in rows:
        if not isinstance(row, dict):
            raise PublicFeedInvalid()
        observed = observation_date(row.get("d"), today)
        if observed in observations:
            raise PublicFeedInvalid()
        values = {}
        for key, series in (("usd_cad", "FXUSDCAD"), ("eur_cad", "FXEURCAD")):
            field = row.get(series)
            if field is not None and (not isinstance(field, dict) or "v" not in field):
                raise PublicFeedInvalid()
            values[key] = number(field.get("v") if field else None)
        observations[observed] = DailyObservation(observed, values)
    return DailyFeed(tuple(observations[d] for d in sorted(observations)), datetime.now(UTC))


def normalize_bitcoin(payload):
    if not isinstance(payload, dict):
        raise PublicFeedInvalid()
    last, opening = number(payload.get("last")), number(payload.get("open"))
    if last is None or opening is None:
        raise PublicFeedInvalid()
    return BitcoinStatistics(last, opening, datetime.now(UTC))


def _unique_object(pairs):
    output = {}
    for key, value in pairs:
        if key in output:
            raise ValueError
        output[key] = value
    return output


def _reject_constant(value):
    raise ValueError


class PublicMarketClient:
    def __init__(self, *, before_request, transport=None):
        self.before_request = before_request
        self.client = httpx.Client(
            timeout=httpx.Timeout(5, connect=3),
            follow_redirects=False,
            trust_env=True,
            transport=transport,
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.client.close()

    def _read(self, url, params=None):
        # Only the three fixed source URLs below can reach this transport.
        self.before_request()
        deadline = time.monotonic() + 10
        try:
            with self.client.stream(
                "GET", url, params=params, headers={"User-Agent": "PortfolioLens/0.31"}
            ) as response:
                if response.status_code == 429:
                    raise ProviderRateLimited(_retry_after(response.headers.get("Retry-After")))
                if response.status_code != 200:
                    raise PublicFeedUnavailable()
                body = bytearray()
                for chunk in response.iter_bytes(4096):
                    body.extend(chunk)
                    if len(body) > MAX_PUBLIC_BYTES or time.monotonic() > deadline:
                        raise PublicFeedUnavailable()
            return bytes(body)
        except httpx.HTTPError:
            raise PublicFeedUnavailable() from None

    def _json(self, url, params=None):
        try:
            return json.loads(
                self._read(url, params),
                parse_float=Decimal,
                parse_constant=_reject_constant,
                object_pairs_hook=_unique_object,
            )
        except (ValueError, UnicodeError, RecursionError):
            raise PublicFeedInvalid() from None

    def treasury(self):
        today = datetime.now(UTC).date()
        raw = self._read(
            TREASURY_URL,
            {"data": "daily_treasury_yield_curve", "field_tdr_date_value": str(today.year)},
        )
        return normalize_treasury(raw, today=today, year=today.year)

    def forex(self):
        return normalize_fx(self._json(FX_URL, {"recent": "5"}), today=datetime.now(UTC).date())

    def bitcoin(self):
        return normalize_bitcoin(self._json(BTC_URL))
