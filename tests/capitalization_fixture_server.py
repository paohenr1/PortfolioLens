"""Explicit synthetic capitalization modes; no production startup imports this."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.fixture_server import main  # noqa: E402


def transport(request):
    import httpx

    from tests.test_capitalization import cap_transport

    mode = sys.argv[1] if len(sys.argv) > 1 else "value"
    if "/historical_data/" in request.url.path:
        if request.url.params["start_date"] == "2015-01-02":
            return httpx.Response(429, headers={"Retry-After": "37"})
    response = cap_transport(request)
    payload = response.json()
    if request.url.path.endswith("/historical_data/marketcap"):
        if mode == "missing":
            payload["historical_data"] = []
        elif mode == "null":
            payload["historical_data"][0]["value"] = None
        elif mode == "zero":
            payload["historical_data"][0]["value"] = 0
        elif mode == "partial":
            payload["next_page"] = "fixture_cursor"
        elif mode == "wrong-date":
            payload["historical_data"][0]["date"] = "2019-12-31"
    elif mode == "wrong-unit":
        payload["unit"] = "eur"
    return httpx.Response(200, json=payload)


if __name__ == "__main__":
    main(capitalization_transport=transport)
