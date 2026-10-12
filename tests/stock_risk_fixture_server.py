"""Synthetic stock observations for optional browser checks, never normal startup."""

import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    import httpx

    from tests.fixture_server import main as serve
    from tests.test_prices import observation, payload
    from tests.test_stock_risk import stock_history

    mode = sys.argv[1]
    values = ["100", "120", "90", "120"] + ["100"] * 17
    adjusted = values
    if mode == "split":
        values = ["100", "50", "55"] + ["55"] * 18
        adjusted = ["50", "50", "55"] + ["55"] * 18
    elif mode == "short":
        values = adjusted = ["100", "90"]
    history = stock_history(values, adjusted=adjusted)
    calls = 0

    def transport(request):
        nonlocal calls
        calls += 1
        if request.url.params.get("start_date") == "2020-03-01":
            return httpx.Response(429, headers={"Retry-After": "60"})
        rows = [
            observation(row.date, close=int(row.close), adjusted=int(row.adjusted_close))
            for row in history.observations
        ]
        cursor = None
        if mode == "gap":
            rows.pop(2)
        elif mode == "unconfirmed":
            rows[2]["intraperiod"] = None
        elif mode == "zero":
            rows[2]["adj_close"] = 0
        elif mode == "partial":
            rows, cursor = rows[calls - 1 : calls], f"page-{calls}"
        data = payload(rows, cursor)
        if mode == "unsupported":
            data["security"]["exchange_mic"] = "XLON"
        return httpx.Response(200, json=data)

    serve(price_transport=transport)


if __name__ == "__main__":
    main()
