"""Synthetic daily volume for optional browser acceptance; no normal fallback."""

import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    import httpx

    from tests.fixture_server import main as serve
    from tests.test_prices import observation, payload

    mode, calls = sys.argv[1], 0

    def transport(request):
        nonlocal calls
        calls += 1
        if request.url.params.get("start_date") == "2020-03-01":
            return httpx.Response(429, headers={"Retry-After": "60"})
        from datetime import date

        rows = [
            {**observation(date(2020, 1, 2), 100, 100), "volume": 1000.125, "adj_volume": 500.0625},
            {**observation(date(2020, 1, 3), 110, 110), "volume": 0, "adj_volume": 0},
            {**observation(date(2020, 1, 6), 99, 99), "volume": 2000, "adj_volume": None},
        ]
        cursor = None
        if mode == "zero":
            for row in rows:
                row["volume"] = row["adj_volume"] = 0
        elif mode == "missing":
            for row in rows:
                row["volume"] = row["adj_volume"] = None
        elif mode == "unconfirmed":
            rows[0]["intraperiod"] = True
            rows[1]["intraperiod"] = None
        elif mode == "volume-only":
            for row in rows:
                row["close"] = row["adj_close"] = None
        elif mode == "partial":
            day = (2, 3, 6, 7)[(calls - 1) % 4]
            rows = [{**observation(date(2020, 1, day)), "volume": 100}]
            cursor = f"page-{calls}"
        elif mode == "empty":
            rows = []
        elif mode == "invalid":
            rows[0]["volume"] = "bad-volume"
        return httpx.Response(200, json=payload(rows, cursor))

    serve(price_transport=transport)


if __name__ == "__main__":
    main()
