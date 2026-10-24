"""Synthetic private browser flow: in-place search, dated holdings and preserved inputs."""

from urllib.parse import urlsplit

from browser_authentication import register
from browser_ledger import submit
from browser_portfolios import create, portfolio_application
from playwright.sync_api import sync_playwright


def main():
    with portfolio_application(ledger_fixtures=True) as base, sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path="/usr/bin/chromium", headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()
        errors, requests = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: requests.append(request.url))
        try:
            register(page, base, "picker-browser-owner")
            portfolio = create(page, base, "Stock picker example")
            record = portfolio + "transactions/record/"
            submit(page, record, "DEPOSIT", 1, "1000")
            page.goto(record + "?mode=trade")
            page.get_by_label("Transaction date:", exact=True).fill("2020-01-02")
            page.get_by_label("Share quantity:", exact=True).fill("10")
            page.get_by_label("Execution price (USD per share):", exact=True).fill("25")
            query = page.get_by_label("Ticker or company name", exact=True)
            before = len([url for url in requests if url.endswith("instruments/search/")])
            query.fill("TSTF")
            assert len([url for url in requests if url.endswith("instruments/search/")]) == before
            query.press("Enter")
            choice = page.locator('.stock-result[data-security-id="sec_fixture_primary"]')
            choice.wait_for()
            assert page.url.endswith("?mode=trade")
            choice.focus()
            page.keyboard.press("Enter")
            assert "TSTF" in page.locator("#stock-selection").inner_text()
            assert not page.get_by_label("Intrinio security ID:", exact=True).is_visible()
            assert page.get_by_label("Share quantity:", exact=True).input_value() == "10"
            assert (
                page.get_by_label("Execution price (USD per share):", exact=True).input_value()
                == "25"
            )
            # Editing the query invalidates a previously selected identity.
            query.fill("Fixture")
            assert not page.locator("#id_security_id").input_value()
            query.press("Enter")
            choice.click()
            page.get_by_label("Share quantity:", exact=True).fill("100")
            page.get_by_role("button", name="Record transaction", exact=True).click()
            assert "would make recorded cash negative" in page.locator("main").inner_text()
            assert query.input_value() == "TSTF"
            assert page.locator("#id_security_id").input_value() == "sec_fixture_primary"
            assert page.get_by_label("Share quantity:", exact=True).input_value() == "100"
            page.get_by_label("Share quantity:", exact=True).fill("10")
            page.get_by_role("button", name="Record transaction", exact=True).click()
            page.get_by_role("heading", name="Transactions", exact=True).wait_for()
            assert "Recorded cash: 750.00 USD" in page.locator("main").inner_text()
            page.goto(record + "?mode=trade")
            page.get_by_label("Transaction type:", exact=True).select_option("SELL")
            page.get_by_label("Transaction date:", exact=True).fill("2020-01-02")
            choice.wait_for()
            assert "10 shares" in choice.inner_text()
            assert "2020-01-02" in page.locator("#stock-selection").inner_text()
            choice.click()
            page.get_by_label("Share quantity:", exact=True).fill("4")
            page.get_by_label("Execution price (USD per share):", exact=True).fill("30")
            page.get_by_role("button", name="Record transaction", exact=True).click()
            page.get_by_role("heading", name="Transactions", exact=True).wait_for()
            assert "Recorded cash: 870.00 USD" in page.locator("main").inner_text()
            page.goto(record + "?mode=trade")
            query.fill("TSTF")
            page.locator(".stock-picker").get_by_role("button", name="Search", exact=True).click()
            choice.wait_for()
            for width in (1280, 390):
                page.set_viewport_size({"width": width, "height": 900})
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert choice.bounding_box()["height"] >= 44
            assert not errors, errors
            assert all(urlsplit(url).hostname == "127.0.0.1" for url in requests)
            print(
                "Stock picker PASS: explicit search, keyboard selection, preserved inputs, "
                "query invalidation, dated sell holdings, accounting and desktop/mobile. "
                "Synthetic transport only."
            )
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
