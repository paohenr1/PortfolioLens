"""Private preferences and daily market reads on owned disposable PostgreSQL DBs."""

from urllib.parse import urlsplit

from browser_authentication import register
from browser_portfolios import portfolio_application
from browser_watchlists import create


def main():
    from playwright.sync_api import sync_playwright

    cases = (
        ("complete", "2020-01-02", "adjusted", "15 USD per share", "240.5", None, 200),
        (
            "missing-fields",
            "2020-01-03",
            "adjusted",
            "Unavailable",
            "Unavailable",
            "not supplied",
            200,
        ),
        ("empty", "2020-01-06", "raw", "Unavailable", "Unavailable", "No daily observation", 200),
        (
            "unconfirmed",
            "2020-01-07",
            "raw",
            "Unavailable",
            "Unavailable",
            "not explicitly marked complete",
            200,
        ),
        ("partial", "2020-01-08", "raw", "Unavailable", "Unavailable", "Incomplete response", 200),
        ("zero", "2020-01-09", "raw", "0 USD per share", "0", None, 200),
        ("rate", "2020-01-10", "raw", "Unavailable", "Unavailable", "request limit", 429),
        (
            "entitlement",
            "2020-01-13",
            "raw",
            "Unavailable",
            "Unavailable",
            "did not grant access",
            200,
        ),
    )
    with sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path="/usr/bin/chromium", headless=True)
        try:
            for mode, day, basis, close, volume, explanation, status in cases:
                with portfolio_application(watchlist_market_fixtures=True) as base:
                    context = browser.new_context(viewport={"width": 1280, "height": 900})
                    requests, errors = [], []
                    context.on("request", lambda r, requests=requests: requests.append(r.url))
                    page = context.new_page()
                    page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
                    try:
                        register(page, base, "market-browser-owner")
                        own_url = create(page, base, "Private market research")
                        page.get_by_role("link", name="Add instrument", exact=True).click()
                        page.get_by_label("Provider instrument ID:", exact=True).fill(
                            "sec_fixture_primary"
                        )
                        page.get_by_role("button", name="Add instrument", exact=True).click()
                        page.get_by_role("link", name="Edit saved preferences", exact=True).click()
                        assert context.request.post(own_url + "preferences/").status == 403
                        page.get_by_label("Default price basis:", exact=True).select_option(
                            "adjusted"
                        )
                        page.get_by_label("Default volume basis:", exact=True).select_option(
                            "adjusted"
                        )
                        page.get_by_label("Instrument order:", exact=True).select_option("ticker")
                        page.get_by_role("button", name="Save preferences", exact=True).focus()
                        page.keyboard.press("Enter")
                        page.get_by_role(
                            "heading", name="Private market research", exact=True
                        ).wait_for()
                        assert "Ticker (A–Z)" in page.locator("main").inner_text()
                        page.get_by_role(
                            "link", name="View daily market information", exact=True
                        ).click()
                        assert (
                            page.get_by_label("Price basis", exact=True).input_value() == "adjusted"
                        )
                        assert (
                            page.get_by_label("Volume basis", exact=True).input_value()
                            == "adjusted"
                        )
                        assert page.locator(".watchlist-market-panel").count() == 0
                        assert page.locator(".statement-form").evaluate(
                            "form => [...form.querySelectorAll('[aria-describedby]')].every("
                            "el => el.getAttribute('aria-describedby').split(/\\s+/).every("
                            "id => document.getElementById(id)))"
                        )
                        page.get_by_label("Daily observation date", exact=True).fill(day)
                        page.get_by_label("Price basis", exact=True).select_option(basis)
                        page.get_by_label("Volume basis", exact=True).select_option(basis)
                        check = page.locator('.watchlist-picker input[type="checkbox"]')
                        check.focus()
                        page.keyboard.press("Space")
                        with page.expect_navigation() as nav:
                            page.get_by_role(
                                "button", name="Load selected market information"
                            ).click()
                        assert nav.value.status == status
                        assert "no-store" in nav.value.headers["cache-control"]
                        panel = page.locator(".watchlist-market-panel")
                        assert panel.locator(".market-close").inner_text() == close
                        assert panel.locator(".market-volume").inner_text() == volume
                        assert day in panel.inner_text()
                        assert "not live quotes" in panel.inner_text()
                        if explanation:
                            assert explanation in panel.inner_text()
                        if status == 429:
                            assert nav.value.headers["retry-after"] == "37"
                        for label, width, height in (("desktop", 1280, 900), ("mobile", 390, 844)):
                            page.set_viewport_size({"width": width, "height": height})
                            assert page.evaluate(
                                "document.documentElement.scrollWidth <= innerWidth"
                            )
                            table = page.get_by_role("region", name="Watchlist market values")
                            table.focus()
                            assert table.evaluate("el=>el===document.activeElement")
                            page.keyboard.press("ArrowRight")
                            page.screenshot(
                                path=f"/tmp/watchlist-market-{mode}-{label}.png", full_page=True
                            )
                        page.goto(own_url + "market/")
                        assert page.locator(".watchlist-market-panel").count() == 0
                        assert (
                            page.get_by_label("Price basis", exact=True).input_value() == "adjusted"
                        )
                        assert not page.locator(
                            '.watchlist-picker input[type="checkbox"]'
                        ).is_checked()
                        # A second real test user cannot access these pages or saved defaults.
                        other = browser.new_context()
                        try:
                            bob = other.new_page()
                            register(bob, base, "market-browser-other")
                            for suffix in ("market/", "preferences/"):
                                response = bob.goto(own_url + suffix)
                                assert response.status == 404
                                assert (
                                    "Private market research"
                                    not in bob.locator("main").inner_text()
                                )
                                assert "no-store" in response.headers["cache-control"]
                        finally:
                            other.close()
                        assert not errors, errors
                        assert all(urlsplit(url).hostname == "127.0.0.1" for url in requests)
                        print(
                            f"Synthetic watchlist {mode}: saved defaults, owner isolation, "
                            "desktop/mobile, exact values and cleanup PASS"
                        )
                    finally:
                        context.close()
        finally:
            browser.close()


if __name__ == "__main__":
    main()
