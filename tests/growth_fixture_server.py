"""Test-only annual-growth variants; never enabled by production settings."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.fixture_server import main  # noqa: E402


def transport(request):
    import httpx

    from tests.test_growth import growth_fixture_transport

    mode = sys.argv[1] if len(sys.argv) > 1 else "positive"
    response = growth_fixture_transport(request)
    if response.status_code != 200:
        return response
    payload = response.json()
    is_values = request.url.path.endswith("/standardized_financials")
    fundamental = payload["fundamental"] if is_values else payload
    prior = fundamental["fiscal_year"] == 2018
    if mode == "mixed-version" and prior:
        fundamental["type"] = "restated"
    if mode == "week-year":
        if prior:
            fundamental["end_date"] = "2018-09-29"
        else:
            fundamental.update(start_date="2018-09-30", end_date="2019-10-05")
    if mode == "stub" and prior:
        fundamental["start_date"] = "2018-04-01"
    if mode == "gap" and not prior:
        fundamental["start_date"] = "2018-10-02"
    if is_values:
        for row in payload["standardized_financials"]:
            tag = row["data_tag"]["tag"]
            if mode == "zero-base" and prior and tag in ("totalrevenue", "netincome"):
                row["value"] = 0
            if tag == "netincome" and mode == "loss-narrows":
                row["value"] = -100 if prior else -50
            if tag == "netincome" and mode == "profit-loss" and not prior:
                row["value"] = -20
        if mode == "partial":
            payload["next_page"] = "fixture_cursor"
    return httpx.Response(200, json=payload)


if __name__ == "__main__":
    main(statement_transport=transport)
