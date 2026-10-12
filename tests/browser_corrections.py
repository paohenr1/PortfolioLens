"""Actual preview/save/audit workflow with invented references in a disposable DB."""

from urllib.parse import urlsplit

from browser_authentication import register
from browser_ledger import fill, submit
from browser_performance import load as load_returns
from browser_portfolios import create, portfolio_application
from browser_valuation import load as load_valuation


def main():
    from playwright.sync_api import sync_playwright

    with portfolio_application(ledger_fixtures=True) as base, sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path="/usr/bin/chromium", headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        other = browser.new_context(viewport={"width": 390, "height": 844})
        requests, errors = [], []
        try:
            page, bob = context.new_page(), other.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            for session in (context, other):
                session.on("request", lambda request: requests.append(request.url))
            register(page, base, "correction-browser-owner")
            register(bob, base, "correction-browser-other")
            portfolio_url = create(page, base, "Correction research")
            foreign_url = create(bob, base, "Other private research")
            history, record = (
                portfolio_url + "transactions/",
                portfolio_url + "transactions/record/",
            )
            submit(page, record, "DEPOSIT", 1, "1000")
            submit(
                page,
                record,
                "BUY",
                2,
                quantity="10",
                price="25",
                fees="1",
                security_id="sec_fixture_primary",
            )
            submit(
                page,
                record,
                "SELL",
                3,
                quantity="4",
                price="30",
                fees="2",
                security_id="sec_fixture_primary",
            )
            assert "Recorded cash: 867.00 USD" in page.locator("main").inner_text()
            buy = page.locator("tbody tr").filter(
                has=page.get_by_role("cell", name="Buy", exact=True)
            )
            buy.get_by_role("link", name="Correct", exact=True).click()
            original_url = page.url
            assert page.get_by_label("Transaction type:", exact=True).input_value() == "BUY"
            assert page.get_by_label("Same-day order:", exact=True).input_value() == "2"
            fill(
                page,
                "BUY",
                2,
                quantity="10",
                price="20",
                fees="1",
                security_id="sec_fixture_primary",
            )
            page.get_by_label("Correction reason:", exact=True).fill(
                "Correct fixture execution price"
            )
            page.get_by_role("button", name="Preview correction", exact=True).click()
            assert "Correction preview" in page.locator("main").inner_text()
            text = page.get_by_role("region", name="Correction accounting preview").inner_text()
            for value in ("867.00", "917.00", "150.60", "120.60", "17.60", "37.60"):
                assert value in text
            for label, width, height in (("desktop", 1280, 900), ("mobile", 390, 844)):
                page.set_viewport_size({"width": width, "height": height})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                page.get_by_role("region", name="Correction accounting preview").focus()
                page.screenshot(path=f"/tmp/stock-correction-preview-{label}.png", full_page=True)
            assert context.request.post(original_url, form={"stage": "save"}).status == 403
            page.get_by_label(
                "I reviewed this correction and its effect on the journal.", exact=True
            ).check()
            saved = page.locator("form.account-form").evaluate(
                "form => Object.fromEntries(new FormData(form))"
            )
            page.get_by_role("button", name="Save correction", exact=True).click()
            page.get_by_role("heading", name="Correction history", exact=True).wait_for()
            assert "Original entry" in page.locator("main").inner_text()
            assert "Replacement entry" in page.locator("main").inner_text()
            assert "Correct fixture execution price" in page.locator("main").inner_text()
            assert context.request.post(original_url, form=saved).status == 200
            page.reload()
            assert page.get_by_role("heading", name="Original entry", exact=True).count() == 1
            for label, width, height in (("desktop", 1280, 900), ("mobile", 390, 844)):
                page.set_viewport_size({"width": width, "height": height})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                page.screenshot(path=f"/tmp/stock-correction-audit-{label}.png", full_page=True)
            audit_url = page.url
            for url in (audit_url, original_url, original_url.replace("/correct/", "/void/")):
                response = bob.goto(url)
                assert response.status == 404
                assert "no-store" in response.headers["cache-control"]
                assert "Correction research" not in bob.locator("main").inner_text()

            load_valuation(page, portfolio_url + "valuation/", "2020-01-02")
            valuation = page.locator("main").inner_text()
            for value in ("917.00", "120.60", "980.00", "-57.60", "93.57", "6.43"):
                assert value in valuation
            load_returns(page, portfolio_url + "performance/", "2020-01-06")
            assert "1.5306%" in page.locator("main").inner_text()

            page.goto(history)
            assert "Recorded cash: 917.00 USD" in page.locator("main").inner_text()
            deposit = page.locator("tbody tr").filter(
                has=page.get_by_role("cell", name="Deposit", exact=True)
            )
            deposit.get_by_role("link", name="Void", exact=True).click()
            page.get_by_label("Correction reason:", exact=True).fill("Fixture invalid funding void")
            page.get_by_role("button", name="Preview correction", exact=True).click()
            assert "cash negative" in page.locator("main").inner_text()
            assert page.get_by_role("button", name="Save correction", exact=True).count() == 0
            page.get_by_role("link", name="Cancel and return to transactions", exact=True).click()
            sale = page.locator("tbody tr").filter(
                has=page.get_by_role("cell", name="Sell", exact=True)
            )
            sale.get_by_role("link", name="Void", exact=True).click()
            page.get_by_label("Correction reason:", exact=True).fill("Void fixture duplicate sale")
            page.get_by_role("button", name="Preview correction", exact=True).click()
            assert "799.00" in page.locator("main").inner_text()
            assert "201.00" in page.locator("main").inner_text()
            page.get_by_label(
                "I reviewed this correction and its effect on the journal.", exact=True
            ).check()
            page.get_by_role("button", name="Save correction", exact=True).click()
            page.get_by_role("heading", name="Correction history", exact=True).wait_for()
            page.goto(history)
            assert page.locator("tbody tr").count() == 2
            assert "Recorded cash: 799.00 USD" in page.locator("main").inner_text()
            submit(
                page,
                record,
                "SELL",
                3,
                quantity="8",
                price="22",
                fees="0",
                security_id="sec_fixture_primary",
            )
            assert "Recorded cash: 975.00 USD" in page.locator("main").inner_text()
            page.goto(portfolio_url + "positions/")
            assert "15.20" in page.locator("main").inner_text()
            assert "40.20" in page.locator("main").inner_text()

            page.goto(history)
            deposit = page.locator("tbody tr").filter(
                has=page.get_by_role("cell", name="Deposit", exact=True)
            )
            deposit.get_by_role("link", name="Correct", exact=True).click()
            deposit_url = page.url
            page.get_by_label("Cash amount (USD):", exact=True).fill("1100")
            page.get_by_label("Correction reason:", exact=True).fill("Fixture stale preview")
            page.get_by_role("button", name="Preview correction", exact=True).click()
            page.get_by_label(
                "I reviewed this correction and its effect on the journal.", exact=True
            ).check()
            stale = page.locator("form.account-form").evaluate(
                "form => Object.fromEntries(new FormData(form))"
            )
            submit(page, record, "FEE", 4, "10")
            response = context.request.post(deposit_url, form=stale)
            assert response.status == 400
            assert "journal changed" in response.text()
            assert "no-store" in response.headers["cache-control"]
            bob.goto(foreign_url)
            bob.get_by_role("button", name="Sign out", exact=True).click()
            bob.goto(audit_url)
            assert "/sign-in/?next=" in bob.url
            assert not errors
            assert all(urlsplit(url).hostname == "127.0.0.1" for url in requests)
            print(
                "Correction browser: exact FIFO/cash preview, signed save/retry, immutable audit, "
                "void/reused order, later append/gains, stale preview, owner/CSRF/sign-out, "
                "desktop/mobile and keyboard controls PASS (synthetic only)"
            )
        finally:
            context.close()
            other.close()
            browser.close()


if __name__ == "__main__":
    main()
