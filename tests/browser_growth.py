"""Optional synthetic-only desktop/mobile annual-growth workflows."""

import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.browser_fundamentals import fixture_application  # noqa: E402


def main():
    from playwright.sync_api import sync_playwright

    cases = (
        ("positive", ["25.00%", "20.00%"], "Dollar change"),
        ("zero-base", ["Unavailable", "Unavailable"], "Break-even to profit"),
        ("loss-narrows", ["25.00%", "Unavailable"], "Loss narrowed"),
        ("profit-loss", ["25.00%", "-120.00%"], "Profit to loss"),
        ("mixed-version", ["25.00%", "20.00%"], "Statement classifications differ"),
        ("week-year", ["25.00%", "20.00%"], "Period lengths differ"),
        ("stub", ["Unavailable", "Unavailable"], "stub periods are unavailable"),
        ("gap", ["Unavailable", "Unavailable"], "without a gap or overlap"),
        ("partial", ["Unavailable", "Unavailable"], "Both statement responses must be complete"),
    )
    with sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path="/usr/bin/chromium", headless=True)
        try:
            for mode, expected, explanation in cases:
                # Each owned process keeps the production request limits.
                with fixture_application(
                    script_name="growth_fixture_server.py", script_args=(mode,)
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
                            "link", name="View annual revenue and earnings growth", exact=True
                        ).click()
                        assert page.locator(".growth-panel").count() == 0
                        assert (
                            "No financial data has been requested yet"
                            in page.locator("main").inner_text()
                        )
                        page.get_by_label("Current fiscal year", exact=True).fill("2019")
                        page.get_by_role("button", name="Load annual growth", exact=True).click()
                        panel = page.locator(".growth-panel")
                        panel.wait_for()
                        assert panel.locator(".metric-value").all_text_contents() == expected
                        assert explanation in panel.inner_text()
                        assert "2018 FY → 2019 FY" in panel.inner_text()
                        assert panel.locator(".growth-sources .metric-card").count() == 2
                        assert "not EPS growth" in panel.inner_text()
                        assert "not a point-in-time backtest dataset" in panel.inner_text()
                        if mode in ("zero-base", "loss-narrows"):
                            assert "the dollar change remains available" in panel.inner_text()
                            earnings = panel.locator(".growth-metrics .metric-card").nth(1)
                            change = earnings.locator("dd").nth(2).inner_text()
                            assert change == ("120" if mode == "zero-base" else "50")
                        for name, width, height in (("desktop", 1280, 900), ("mobile", 390, 844)):
                            page.set_viewport_size({"width": width, "height": height})
                            assert page.evaluate(
                                "document.documentElement.scrollWidth <= window.innerWidth"
                            )
                            for card in panel.locator(".metric-card").all():
                                assert card.is_visible()
                            page.screenshot(
                                path=f"/tmp/stock-growth-{mode}-{name}.png", full_page=True
                            )
                        response = page.goto(
                            base + "/stocks/sec_fixture_primary/growth/?fiscal_year=2015"
                        )
                        assert response.status == 429
                        assert response.headers["cache-control"] == "no-store"
                        assert page.locator(".growth-panel").count() == 0
                        assert page.get_by_role("alert").is_visible()
                        assert not errors, errors
                        assert all(urlsplit(url).hostname == "127.0.0.1" for url in requests)
                        print(
                            f"Test-only annual growth {mode}: desktop/mobile, "
                            "periods, bases, sources, error cleanup PASS"
                        )
                    finally:
                        page.close()
        finally:
            browser.close()


if __name__ == "__main__":
    main()
