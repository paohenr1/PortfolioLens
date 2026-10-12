"""Optional desktop/mobile annual-return checks using only synthetic observations."""

import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.browser_fundamentals import fixture_application  # noqa: E402


def main():
    from playwright.sync_api import sync_playwright

    cases = (
        ("positive", ["10.91%", "20.00%"], "Average balance"),
        ("zero", ["0.00%", "0.00%"], "Selected-period net income"),
        ("loss", ["-10.91%", "-20.00%"], "Selected-period net income"),
        ("zero-equity", ["10.91%", "Unavailable"], "Both endpoint balances must be positive"),
        ("misaligned", ["Unavailable", "Unavailable"], "day before income starts"),
        (
            "partial",
            ["Unavailable", "Unavailable"],
            "All three statement responses must be complete",
        ),
    )
    with sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path="/usr/bin/chromium", headless=True)
        try:
            for mode, expected, explanation in cases:
                # A fresh process keeps each scenario inside the actual quota.
                with fixture_application(
                    script_name="capital_fixture_server.py", script_args=(mode,)
                ) as base:
                    page = browser.new_page(viewport={"width": 1280, "height": 900})
                    requests, errors = [], []
                    page.on(
                        "request", lambda request, requests=requests: requests.append(request.url)
                    )
                    page.on("pageerror", lambda error, errors=errors: errors.append(str(error)))
                    try:
                        page.goto(base + "/stocks/sec_fixture_primary/financials/")
                        page.get_by_role(
                            "link", name="View return on assets and equity", exact=True
                        ).click()
                        assert page.locator(".capital-returns-panel").count() == 0
                        assert (
                            "No financial data has been requested yet"
                            in page.locator("main").inner_text()
                        )
                        page.get_by_label("Fiscal year", exact=True).fill("2019")
                        page.get_by_role("button", name="Load annual returns", exact=True).click()
                        panel = page.locator(".capital-returns-panel")
                        panel.wait_for()
                        assert panel.locator(".metric-value").all_text_contents() == expected
                        assert explanation in panel.inner_text()
                        assert "2018-10-01" in panel.inner_text()
                        assert "2019-09-30" in panel.inner_text()
                        assert panel.locator(".capital-sources .metric-card").count() == 3
                        assert "not a daily average" in panel.inner_text()
                        assert "Filing dates do not establish" in panel.inner_text()
                        for name, width, height in (("desktop", 1280, 900), ("mobile", 390, 844)):
                            page.set_viewport_size({"width": width, "height": height})
                            assert page.evaluate(
                                "document.documentElement.scrollWidth <= window.innerWidth"
                            )
                            for card in panel.locator(".metric-card").all():
                                assert card.is_visible()
                            page.screenshot(
                                path=f"/tmp/stock-capital-{mode}-{name}.png", full_page=True
                            )
                        response = page.goto(
                            base
                            + "/stocks/sec_fixture_primary/returns-on-capital/?fiscal_year=2015"
                        )
                        assert response.status == 429
                        assert response.headers["cache-control"] == "no-store"
                        assert page.locator(".capital-returns-panel").count() == 0
                        assert page.get_by_role("alert").is_visible()
                        assert not errors, errors
                        assert all(urlsplit(url).hostname == "127.0.0.1" for url in requests)
                        print(
                            f"Test-only annual returns {mode}: desktop/mobile, "
                            "sources, quota/error cleanup PASS"
                        )
                    finally:
                        page.close()
        finally:
            browser.close()


if __name__ == "__main__":
    main()
