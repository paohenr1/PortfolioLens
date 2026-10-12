"""Explicit test-only annual statement variants; never used by normal startup."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.fixture_server import main  # noqa: E402


def transport(request):
    import httpx

    from tests.test_trends import trend_fixture_transport

    mode = sys.argv[1] if len(sys.argv) > 1 else "normal"
    if "/fundamentals/lookup/" in request.url.path and "/2015/FY" in request.url.path:
        return httpx.Response(429, headers={"Retry-After": "37"})
    response = trend_fixture_transport(request)
    if response.status_code != 200:
        return response
    payload = response.json()
    values = request.url.path.endswith("/standardized_financials")
    period = payload["fundamental"] if values else payload
    year = period["fiscal_year"]
    if mode == "mixed" and year == 2018:
        period["type"] = "restated"
    if mode == "gap" and year == 2018:
        period["start_date"] = "2017-10-02"
    if mode == "stub" and year == 2018:
        period["start_date"] = "2018-04-01"
    if mode == "week":
        dates = {
            2017: ("2016-09-25", "2017-09-23"),
            2018: ("2017-09-24", "2018-09-29"),
            2019: ("2018-09-30", "2019-09-28"),
        }
        period["start_date"], period["end_date"] = dates[year]
    if values and year == 2018:
        if mode == "partial":
            payload["next_page"] = "fixture_cursor"
        if mode == "missing":
            payload["standardized_financials"] = [
                row
                for row in payload["standardized_financials"]
                if row["data_tag"]["tag"] != "netincome"
            ]
    return httpx.Response(200, json=payload)


if __name__ == "__main__":
    main(statement_transport=transport)
