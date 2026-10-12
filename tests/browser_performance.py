"""Private return workflow on a disposable DB with explicitly synthetic daily prices."""

from urllib.parse import urlsplit

from browser_authentication import register
from browser_ledger import fill, submit
from browser_portfolios import create, portfolio_application


def load(page, url, end="2020-01-08"):
    page.goto(url)
    page.get_by_label("Opening valuation date:", exact=True).fill("2020-01-02")
    page.get_by_label("Closing valuation date:", exact=True).fill(end)
    page.locator("#id_timing_checked").check()
    page.get_by_role("button", name="Load returns", exact=True).click()


def main():
    from playwright.sync_api import sync_playwright

    with portfolio_application(ledger_fixtures=True) as base, sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path="/usr/bin/chromium", headless=True)
        owner = browser.new_context(viewport={"width": 1280, "height": 900})
        other = browser.new_context(viewport={"width": 390, "height": 844})
        errors, requests = [], []
        try:
            page, bob = owner.new_page(), other.new_page()
            for context in (owner, other):
                context.on("request", lambda request: requests.append(request.url))
            for current in (page, bob):
                current.on("pageerror", lambda error: errors.append(str(error)))
            register(page, base, "performance-browser-alice")
            register(bob, base, "performance-browser-bob")
            portfolio = create(page, base, "Performance example")
            page.get_by_role("link", name="View time-weighted returns", exact=True).click()
            url = page.url
            assert page.locator(".reference-grid").count() == 0
            load(page, url)
            assert page.locator(".reference-grid dd").all_text_contents() == ["Unavailable"]
            assert "positive opening value" in page.locator("main").inner_text()
            record_url = portfolio + "transactions/record/"
            submit(page, record_url, "DEPOSIT", 1, "1000")
            load(page, url)
            assert page.locator(".reference-grid dd").all_text_contents() == ["0.0000%"]
            submit(
                page,
                record_url,
                "BUY",
                2,
                quantity="10",
                price="10",
                fees="0",
                security_id="sec_fixture_primary",
            )
            page.goto(record_url)
            fill(page, "DEPOSIT", 1, "50")
            page.get_by_label("Transaction date:", exact=True).fill("2020-01-06")
            page.get_by_role("button", name="Record transaction", exact=True).click()
            page.get_by_role("heading", name="Transactions", exact=True).wait_for()
            load(page, url)
            page.get_by_role("heading", name="Subperiod calculations", exact=True).wait_for()
            assert page.locator(".reference-grid dd").all_text_contents() == ["4.8600%"]
            table = page.get_by_role("region", name="Return subperiod table", exact=True)
            assert table.locator("tbody tr").count() == 2
            assert table.locator("tbody tr").nth(0).locator("td").all_text_contents() == [
                "2020-01-02",
                "2020-01-06",
                "1005.00",
                "1080.00",
                "50.00",
                "1030.00",
                "2.4876%",
            ]
            assert table.locator("tbody tr").nth(1).locator("td").all_text_contents() == [
                "2020-01-06",
                "2020-01-08",
                "1080.00",
                "1105.00",
                "0",
                "1105.00",
                "2.3148%",
            ]
            for label, width, height in (("desktop", 1280, 900), ("mobile", 390, 844)):
                page.set_viewport_size({"width": width, "height": height})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                table.focus()
                assert table.evaluate("el => el === document.activeElement")
                page.keyboard.press("ArrowRight")
                page.get_by_text("2020-01-02 · Total value 1005.00 USD", exact=True).click()
                assert "Confirmed daily close 2020-01-02" in page.locator("main").inner_text()
                page.screenshot(path=f"/tmp/stock-performance-{label}.png", full_page=True)
                page.get_by_text("2020-01-02 · Total value 1005.00 USD", exact=True).click()
            load(page, url, "2020-01-09")
            assert page.locator(".reference-grid dd").all_text_contents() == ["Unavailable"]
            assert "complete-period return is unavailable" in page.locator("main").inner_text()
            # A same-day deposit funding a later buy must fail before price loading.
            for kind, sequence in (("DEPOSIT", 1), ("BUY", 2)):
                page.goto(record_url)
                fill(
                    page,
                    kind,
                    sequence,
                    "10" if kind == "DEPOSIT" else "",
                    quantity="1" if kind == "BUY" else "",
                    price="10" if kind == "BUY" else "",
                    security_id="sec_fixture_primary" if kind == "BUY" else "",
                )
                page.get_by_label("Transaction date:", exact=True).fill("2020-01-07")
                page.get_by_role("button", name="Record transaction", exact=True).click()
                page.get_by_role("heading", name="Transactions", exact=True).wait_for()
            load(page, url)
            assert "must follow all other same-day activity" in page.locator("main").inner_text()
            assert page.locator(".reference-grid").count() == 0
            response = bob.goto(url)
            assert response.status == 404
            assert "Performance example" not in bob.locator("main").inner_text()
            assert "no-store" in response.headers["cache-control"]
            response = owner.request.post(
                url,
                form={"start_date": "2020-01-02", "end_date": "2020-01-08", "timing_checked": "on"},
            )
            assert response.status == 403
            page.get_by_role("button", name="Sign out", exact=True).click()
            page.goto(url)
            assert "/sign-in/?next=" in page.url
            assert not errors
            assert all(urlsplit(request).hostname == "127.0.0.1" for request in requests)
            print(
                "Performance browser: EOD deposit adjustment/exact linked return, cash-only and "
                "zero baseline, missing close, intraday rejection, provenance, owners, CSRF, "
                "sign-out and desktop/mobile keyboard table PASS (synthetic only)"
            )
        finally:
            owner.close()
            other.close()
            browser.close()


if __name__ == "__main__":
    main()
