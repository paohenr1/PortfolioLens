"""Isolated real PostgreSQL journal workflow; instrument data is explicitly synthetic."""

from urllib.parse import urlsplit

from browser_authentication import register
from browser_portfolios import create, portfolio_application


def fill(page, kind, sequence, amount="", *, quantity="", price="", fees="0", security_id=""):
    page.get_by_label("Transaction currency:", exact=True).select_option("USD")
    page.get_by_label("Transaction type:", exact=True).select_option(kind)
    page.get_by_label("Transaction date:", exact=True).fill("2020-01-02")
    page.get_by_label("Same-day order:", exact=True).fill(str(sequence))
    page.get_by_label("Cash amount (USD):", exact=True).fill(amount)
    page.get_by_label("Intrinio security ID:", exact=True).fill(security_id)
    page.get_by_label("Share quantity:", exact=True).fill(quantity)
    page.get_by_label("Execution price (USD per share):", exact=True).fill(price)
    page.get_by_label("Trade fees (USD):", exact=True).fill(fees)


def submit(page, record_url, kind, sequence, amount="", **extra):
    page.goto(record_url)
    fill(page, kind, sequence, amount, **extra)
    page.get_by_role("button", name="Record transaction", exact=True).click()
    page.get_by_role("heading", name="Transactions", exact=True).wait_for()


def main():
    from playwright.sync_api import sync_playwright

    with portfolio_application(ledger_fixtures=True) as base, sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path="/usr/bin/chromium", headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        other = browser.new_context(viewport={"width": 390, "height": 844})
        errors, requests = [], []
        try:
            page, bob = context.new_page(), other.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            for session in (context, other):
                session.on("request", lambda request: requests.append(request.url))
            register(page, base, "ledger-browser-alice")
            register(bob, base, "ledger-browser-bob")
            portfolio_url = create(page, base, "Transaction fixture")
            page.get_by_role("link", name="View transactions", exact=True).click()
            history_url = page.url
            record_url = history_url + "record/"
            assert page.get_by_role("heading", name="No transactions yet").is_visible()
            submit(page, record_url, "DEPOSIT", 1, "1000")
            assert "Recorded cash: 1000.00 USD" in page.locator("main").inner_text()
            page.goto(record_url)
            fill(
                page,
                "BUY",
                2,
                quantity="10",
                price="25",
                fees="1",
                security_id="sec_fixture_primary",
            )
            submission = page.locator("form.account-form").evaluate(
                "form => Object.fromEntries(new FormData(form))"
            )
            page.get_by_role("button", name="Record transaction", exact=True).click()
            page.get_by_role("heading", name="Transactions", exact=True).wait_for()
            assert "Recorded cash: 749.00 USD" in page.locator("main").inner_text()
            assert "TSTF" in page.get_by_role("table").inner_text()
            response = context.request.post(record_url, form=submission)
            assert response.status == 200
            page.goto(history_url)
            assert page.locator("tbody tr").count() == 2
            assert "Recorded cash: 749.00 USD" in page.locator("main").inner_text()
            submit(
                page,
                record_url,
                "SELL",
                3,
                quantity="4",
                price="30",
                fees="2",
                security_id="sec_fixture_primary",
            )
            submit(page, record_url, "FEE", 4, "3")
            submit(page, record_url, "WITHDRAWAL", 5, "100")
            assert "Recorded cash: 764.00 USD" in page.locator("main").inner_text()
            assert page.locator("tbody tr").count() == 5

            for name, width, height in (("desktop", 1280, 900), ("mobile", 390, 844)):
                page.set_viewport_size({"width": width, "height": height})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                page.locator(".table-scroll").focus()
                assert page.locator(".table-scroll").evaluate("el => el === document.activeElement")
                page.screenshot(path=f"/tmp/stock-ledger-history-{name}.png", full_page=True)
                page.goto(record_url)
                fill(page, "SELL", 6, quantity="7", price="30", security_id="sec_fixture_primary")
                page.get_by_role("button", name="Record transaction", exact=True).click()
                assert "would create a short position" in page.locator("main").inner_text()
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                page.screenshot(path=f"/tmp/stock-ledger-validation-{name}.png", full_page=True)
                page.goto(history_url)
                assert page.locator("tbody tr").count() == 5
                assert "Recorded cash: 764.00 USD" in page.locator("main").inner_text()
            for url in (history_url, record_url):
                response = bob.goto(url)
                assert response.status == 404
                assert "Transaction fixture" not in bob.locator("main").inner_text()
            page.get_by_role("button", name="Sign out", exact=True).click()
            page.goto(history_url)
            assert "/sign-in/?next=" in page.url
            assert not errors
            assert all(urlsplit(url).hostname == "127.0.0.1" for url in requests)
            assert portfolio_url.startswith(base)
            print(
                "PostgreSQL ledger browser: cash/buy/sell/fees, exact retry, oversell rejection, "
                "owner isolation, desktop/mobile and keyboard table PASS (synthetic reference only)"
            )
        finally:
            context.close()
            other.close()
            browser.close()


if __name__ == "__main__":
    main()
