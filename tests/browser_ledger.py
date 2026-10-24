"""Isolated real PostgreSQL journal workflow; instrument data is explicitly synthetic."""

from urllib.parse import urlsplit

from browser_authentication import register
from browser_portfolios import create, portfolio_application


def fill(page, kind, sequence, amount="", *, quantity="", price="", fees="0", security_id=""):
    regular = kind in {"BUY", "SELL", "DEPOSIT", "WITHDRAWAL"}
    if regular:
        mode = "Buy / Sell" if kind in {"BUY", "SELL"} else "Deposit / Withdraw"
        if not page.locator(f'#id_kind option[value="{kind}"]').count():
            page.get_by_role("link", name=mode, exact=True).click()
        page.get_by_label("Transaction type:", exact=True).select_option(kind)
    else:
        # Historical accounting fixtures use the supported explicit-order payload;
        # Fee/Dividend/Split are deliberately absent from the regular entry UI.
        page.locator("#id_kind").evaluate(
            "(el, kind) => { el.add(new Option(kind, kind)); el.value = kind; }", kind
        )
        page.locator("form.account-form").evaluate(
            "(form, order) => { const input = document.createElement('input'); "
            "input.type='hidden'; input.name='sequence'; input.value=order; form.append(input); }",
            str(sequence),
        )
    page.get_by_label("Transaction date:", exact=True).fill("2020-01-02")
    if regular and security_id and page.locator(".stock-picker").is_visible():
        if security_id == "sec_fixture_primary":
            page.get_by_label("Ticker or company name", exact=True).fill("TSTF")
            page.locator(".stock-picker").get_by_role("button", name="Search", exact=True).click()
            page.locator(f'.stock-result[data-security-id="{security_id}"]').click()
        else:
            # Other analytics fixtures predate the picker search fixture's listings.
            page.locator("#stock-query").fill(security_id)
            page.locator("#id_security_id").evaluate("(el, value) => el.value = value", security_id)

    values = {
        "currency": "USD",
        "amount": amount,
        "security_id": security_id,
        "quantity": quantity,
        "unit_price": price,
        "fees": fees,
    }
    for name, value in values.items():
        field = page.locator("#id_" + name)
        if field.is_visible():
            field.fill(value)
        elif not regular:
            field.evaluate("(el, value) => el.value = value", value)


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
            page.goto(record_url)
            assert page.get_by_label("Cash amount (USD):", exact=True).is_visible()
            assert not page.get_by_label("Intrinio security ID:", exact=True).is_visible()
            assert not page.locator('[name="sequence"]').count()
            page.get_by_role("link", name="Buy / Sell", exact=True).click()
            assert page.get_by_label("Share quantity:", exact=True).is_visible()
            assert not page.locator('#id_kind option[value="SPLIT"]').count()
            assert not page.get_by_label("Cash amount (USD):", exact=True).is_visible()
            page.goto(portfolio_url)
            page.get_by_label("Opening valuation date:", exact=True).fill("2020-01-06")
            page.get_by_label("Closing valuation date:", exact=True).fill("2020-01-08")
            page.get_by_role("checkbox").check()
            page.get_by_role("button", name="Update valuation & performance", exact=True).click()
            assert page.get_by_role("heading", name="Transaction fixture", exact=True).is_visible()
            assert "857.00" in page.locator(".portfolio-inline-values").inner_text()
            assert "1.7815%" in page.locator(".portfolio-inline-values").inner_text()
            assert page.get_by_role("region", name="Holding market values").is_visible()
            assert page.locator("main table").count() == 1
            assert not page.locator(".portfolio-analysis-links").is_visible()
            update = page.get_by_role("button", name="Update valuation & performance")
            assert update.bounding_box()["height"] >= 44
            for theme in ("dark", "light"):
                page.get_by_role("combobox", name="Color theme").select_option(theme)
                for width in (1280, 390):
                    page.set_viewport_size({"width": width, "height": 900})
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path="/tmp/stock-portfolio-inline-mobile.png", full_page=True)
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
