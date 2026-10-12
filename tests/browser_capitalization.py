"""Actual desktop/mobile company-cap flows, with explicitly synthetic sources."""

import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.browser_fundamentals import fixture_application  # noqa: E402


def main():
    from playwright.sync_api import sync_playwright

    cases = (
        ("value", "3,000,000,000,000.125", None),
        ("zero", "0", None),
        ("missing", "Unavailable", "No market capitalization observation"),
        ("null", "Unavailable", "no market capitalization value"),
        ("partial", "Unavailable", "response is incomplete"),
        ("wrong-unit", None, "could not be validated"),
        ("wrong-date", None, "could not be validated"),
    )
    with sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path="/usr/bin/chromium", headless=True)
        try:
            for mode, expected, explanation in cases:
                with fixture_application(
                    script_name="capitalization_fixture_server.py", script_args=(mode,)
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
                            "link", name="View company market capitalization", exact=True
                        ).click()
                        assert page.locator(".capitalization-panel").count() == 0
                        page.get_by_label("Market capitalization date", exact=True).fill("")
                        page.get_by_role("button", name="Load market capitalization").click()
                        assert page.locator(".capitalization-panel").count() == 0
                        page.get_by_label("Market capitalization date", exact=True).fill(
                            "2020-01-02"
                        )
                        with page.expect_navigation() as loaded:
                            page.get_by_role("button", name="Load market capitalization").click()
                        assert loaded.value.status == (503 if expected is None else 200)
                        if expected is None:
                            assert page.locator(".capitalization-panel").count() == 0
                            assert explanation in page.get_by_role("alert").inner_text()
                        else:
                            panel = page.locator(".capitalization-panel")
                            assert panel.locator(".metric-value").inner_text() == expected
                            for text in (
                                "2020-01-02",
                                "Underlying price date",
                                "Underlying shares-outstanding count",
                                "not supplied by this endpoint",
                                "USD",
                                "marketcap / usd",
                                "historical-as-known",
                            ):
                                assert text in panel.inner_text()
                            if explanation:
                                assert explanation in panel.inner_text()
                        for name, width, height in (("desktop", 1280, 900), ("mobile", 390, 844)):
                            page.set_viewport_size({"width": width, "height": height})
                            assert page.evaluate(
                                "document.documentElement.scrollWidth <= window.innerWidth"
                            )
                            page.get_by_label("Market capitalization date", exact=True).focus()
                            assert page.get_by_label(
                                "Market capitalization date", exact=True
                            ).evaluate("el => el === document.activeElement")
                            page.screenshot(
                                path=f"/tmp/stock-cap-{mode}-{name}.png", full_page=True
                            )
                        if expected is not None:
                            response = page.goto(
                                base + "/stocks/sec_fixture_primary/market-cap/"
                                "?valuation_date=2015-01-02"
                            )
                            assert response.status == 429
                            assert response.headers["retry-after"] == "37"
                            assert response.headers["cache-control"] == "no-store"
                            assert page.locator(".capitalization-panel").count() == 0
                        assert not errors, errors
                        assert all(urlsplit(url).hostname == "127.0.0.1" for url in requests)
                        print(f"Synthetic cap {mode}: desktop/mobile, dates, sources, errors PASS")
                    finally:
                        page.close()
        finally:
            browser.close()


if __name__ == "__main__":
    main()
