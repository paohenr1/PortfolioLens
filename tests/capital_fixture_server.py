"""Test-only statement variants; never used by normal application startup."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.fixture_server import main  # noqa: E402


def transport(request):
    import httpx

    from tests.test_capital_returns import capital_fixture_transport

    mode = sys.argv[1] if len(sys.argv) > 1 else "positive"
    response = capital_fixture_transport(request)
    if response.status_code != 200:
        return response
    payload = response.json()
    is_values = request.url.path.endswith("/standardized_financials")
    fundamental = payload["fundamental"] if is_values else payload
    if mode == "misaligned" and fundamental["statement_code"] == "balance_sheet_statement":
        if fundamental["fiscal_year"] == 2018:
            fundamental["end_date"] = "2018-09-29"
    if is_values:
        for row in payload["standardized_financials"]:
            if row["data_tag"]["tag"] == "netincome" and mode in ("zero", "loss"):
                row["value"] = 0 if mode == "zero" else -120
            if row["data_tag"]["tag"] == "totalequity" and mode == "zero-equity":
                row["value"] = 0
        if mode == "partial":
            payload["next_page"] = "fixture_cursor"
    return httpx.Response(200, json=payload)


if __name__ == "__main__":
    main(statement_transport=transport)
