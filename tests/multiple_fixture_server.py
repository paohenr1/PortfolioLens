"""Explicit synthetic P/E variants; production startup never imports this."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.fixture_server import main  # noqa: E402


def transport(request):
    import httpx

    from tests.test_multiples import multiple_fixture_transport

    mode = sys.argv[1] if len(sys.argv) > 1 else "positive"
    if "/fundamentals/lookup/" in request.url.path and "/2015/" in request.url.path:
        return httpx.Response(429, headers={"Retry-After": "37"})
    response = multiple_fixture_transport(request)
    if response.status_code != 200:
        return response
    payload = response.json()
    if request.url.path.endswith("/prices"):
        if mode == "partial-price":
            payload["next_page"] = "fixture_cursor"
        if mode == "uncertain-price":
            payload["stock_prices"][0]["intraperiod"] = None
        if mode == "zero-price":
            payload["stock_prices"][0]["close"] = 0
        if mode == "non-usd-price":
            payload["security"]["currency"] = "EUR"
    else:
        values = request.url.path.endswith("/standardized_financials")
        period = payload["fundamental"] if values else payload
        if mode == "stub":
            period["start_date"] = "2019-04-01"
        if mode == "restated":
            period["type"] = "restated"
        if values:
            for row in payload["standardized_financials"]:
                if row["data_tag"]["tag"] == "basiceps":
                    if mode == "zero-eps":
                        row["value"] = 0
                    if mode == "loss-eps":
                        row["value"] = -2
                    if mode == "null-eps":
                        row["value"] = None
                    if mode == "wrong-eps-unit":
                        row["data_tag"]["unit"] = "usd"
    return httpx.Response(200, json=payload)


if __name__ == "__main__":
    main(statement_transport=transport, price_transport=transport)
