"""Optional actual desktop/mobile P/E checks with labeled synthetic data."""

import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.browser_fundamentals import fixture_application  # noqa: E402


def main():
    from playwright.sync_api import sync_playwright

    cases = (
        ("positive", ["15.00×", "20.00×"], "2019 FY P/E"),
        ("restated", ["15.00×", "20.00×"], "restated"),
        ("zero-eps", ["Unavailable", "20.00×"], "positive EPS"),
        ("loss-eps", ["Unavailable", "20.00×"], "negative earnings"),
        ("null-eps", ["Unavailable", "20.00×"], "Source value basiceps"),
        ("wrong-eps-unit", ["Unavailable", "20.00×"], "unit of usdpershare"),
        ("zero-price", ["0.00×", "0.00×"], "Confirmed raw close"),
        ("uncertain-price", ["Unavailable", "Unavailable"], "confirmed raw USD close"),
        ("partial-price", ["Unavailable", "Unavailable"], "Partial price response"),
        ("non-usd-price", ["Unavailable", "Unavailable"], "raw USD close"),
        ("stub", ["Unavailable", "Unavailable"], "stub periods are unavailable"),
    )
    with sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path="/usr/bin/chromium", headless=True)
        try:
            for mode, expected, explanation in cases:
                with fixture_application(
                    script_name="multiple_fixture_server.py", script_args=(mode,)
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
                            "link", name="View annual earnings valuation multiples", exact=True
                        ).click()
                        assert page.locator(".multiples-panel").count() == 0
                        confirmation = page.get_by_role("checkbox")
                        assert not confirmation.is_checked()
                        page.get_by_label("Earnings fiscal year", exact=True).fill("2019")
                        page.get_by_label("Raw closing price date", exact=True).fill("2020-01-02")
                        # Browser validation refuses unconfirmed share assumptions.
                        page.get_by_role("button", name="Load annual P/E", exact=True).click()
                        assert page.locator(".multiples-panel").count() == 0
                        assert page.evaluate(
                            "document.querySelector('[type=checkbox]').validity.valueMissing"
                        )
                        confirmation.focus()
                        page.keyboard.press("Space")
                        page.get_by_role("button", name="Load annual P/E", exact=True).click()
                        panel = page.locator(".multiples-panel")
                        panel.wait_for()
                        assert panel.locator(".metric-value").all_text_contents() == expected
                        assert explanation in panel.inner_text()
                        for text in (
                            "2019-09-30",
                            "2020-01-02",
                            "historical-as-known",
                            "not independently verified",
                            "USD per share",
                        ):
                            assert text in panel.inner_text()
                        assert panel.locator(".multiples-sources .metric-card").count() == 2
                        if mode == "loss-eps":
                            assert (
                                panel.locator(".multiples-metrics .metric-card")
                                .first.locator("dd")
                                .inner_text()
                                == "-2"
                            )
                        for name, width, height in (("desktop", 1280, 900), ("mobile", 390, 844)):
                            page.set_viewport_size({"width": width, "height": height})
                            assert page.evaluate(
                                "document.documentElement.scrollWidth <= window.innerWidth"
                            )
                            for card in panel.locator(".metric-card").all():
                                assert card.is_visible()
                            page.screenshot(
                                path=f"/tmp/stock-multiples-{mode}-{name}.png", full_page=True
                            )
                        response = page.goto(
                            base + "/stocks/sec_fixture_primary/multiples/?fiscal_year=2015"
                            "&price_date=2020-01-02&basis_confirmed=on"
                        )
                        assert response.status == 429
                        assert response.headers["retry-after"] == "37"
                        assert response.headers["cache-control"] == "no-store"
                        assert page.locator(".multiples-panel").count() == 0
                        assert page.get_by_role("alert").is_visible()
                        assert not errors, errors
                        assert all(urlsplit(url).hostname == "127.0.0.1" for url in requests)
                        print(
                            f"Test-only annual P/E {mode}: desktop/mobile, confirmation, "
                            "dates, sources, unavailable states and cleanup PASS"
                        )
                    finally:
                        page.close()
        finally:
            browser.close()


if __name__ == "__main__":
    main()
