"""Optional desktop/mobile checks; synthetic statement data stays test-only."""

import sys
from pathlib import Path
from urllib.parse import urlencode, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.browser_fundamentals import fixture_application  # noqa: E402


def main():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path="/usr/bin/chromium", headless=True)
        try:
            for year, period in ((2019, "FY"), (2019, "Q2"), (2018, "FY")):
                # Each process retains the production quota. No provider key,
                # persistence, external requests or quota bypass is needed.
                with fixture_application() as base:
                    page = browser.new_page(viewport={"width": 1280, "height": 900})
                    requests, errors = [], []
                    page.on(
                        "request", lambda request, requests=requests: requests.append(request.url)
                    )
                    page.on("pageerror", lambda error, errors=errors: errors.append(str(error)))
                    try:
                        route = base + "/stocks/sec_fixture_primary/financials/"
                        response = page.goto(route)
                        assert response.status == 200
                        assert page.locator(".profitability-panel").count() == 0
                        page.get_by_label("Fiscal year", exact=True).fill(str(year))
                        page.get_by_label("Fiscal period", exact=True).select_option(period)
                        page.get_by_role("button", name="Load statement", exact=True).click()
                        panel = page.locator(".profitability-panel")
                        panel.wait_for()
                        values = panel.locator(".metric-value").all_text_contents()
                        expected = (
                            ["Unavailable", "Unavailable", "-0.02%"]
                            if year == 2019
                            else ["Unavailable"] * 3
                        )
                        assert values == expected, values
                        assert f"{year} {period}" in panel.inner_text()
                        assert "no annualization" in panel.inner_text()
                        assert "not a historical as-of snapshot" in panel.inner_text()
                        if year == 2019:
                            assert (
                                "Source tag totalgrossprofit was not supplied" in panel.inner_text()
                            )
                            assert (
                                "Source tag totaloperatingincome was not supplied"
                                in panel.inner_text()
                            )
                        else:
                            assert (
                                "No financial values supplied" in page.locator("main").inner_text()
                            )
                        for name, width, height in (("desktop", 1280, 900), ("mobile", 390, 844)):
                            page.set_viewport_size({"width": width, "height": height})
                            assert page.evaluate(
                                "document.documentElement.scrollWidth <= window.innerWidth"
                            )
                            for card in panel.locator(".metric-card").all():
                                assert card.is_visible()
                            page.screenshot(
                                path=f"/tmp/stock-profitability-{year}-{period}-{name}.png",
                                full_page=True,
                            )
                        response = page.goto(
                            route
                            + "?"
                            + urlencode(
                                {
                                    "statement_code": "income_statement",
                                    "fiscal_year": 2015,
                                    "fiscal_period": "FY",
                                }
                            )
                        )
                        assert response.status == 429
                        assert response.headers["cache-control"] == "no-store"
                        assert page.locator(".profitability-panel").count() == 0
                        assert page.get_by_role("alert").is_visible()
                        assert not errors, errors
                        assert all(urlsplit(url).hostname == "127.0.0.1" for url in requests)
                        print(
                            f"Test-only profitability {year} {period}: desktop/mobile, "
                            "period, missing tags, rate-limit cleanup PASS"
                        )
                    finally:
                        page.close()
        finally:
            browser.close()


if __name__ == "__main__":
    main()
