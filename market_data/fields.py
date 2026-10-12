"""Shared bounded reference fields and opaque provider identifiers."""

import re

from market_data.errors import InvalidResponse

_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,100}")


def valid_provider_id(value: str) -> bool:
    return isinstance(value, str) and _IDENTIFIER.fullmatch(value) is not None


def optional_text(payload: dict, key: str, *, limit: int = 512) -> str | None:
    value = payload.get(key)
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value) > limit:
        raise InvalidResponse()
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise InvalidResponse()
    return value.strip() or None


def optional_boolean(payload: dict, key: str) -> bool | None:
    value = payload.get(key)
    if value is not None and not isinstance(value, bool):
        raise InvalidResponse()
    return value
