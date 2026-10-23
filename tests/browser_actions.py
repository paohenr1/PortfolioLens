"""Recorded split/dividend workflows with synthetic references in an owned temporary DB."""

from urllib.parse import urlsplit

from browser_authentication import register
from browser_ledger import fill, submit
from browser_portfolios import create, portfolio_application


def record_action(page, record_url, kind, order, *, new="", old="", amount=""):
    page.goto(record_url)
    fill(page, kind, order, amount, security_id="sec_fixture_primary")
    if kind == "SPLIT":
        page.locator("#id_split_new").evaluate("(el, value) => el.value = value", new)
        page.locator("#id_split_old").evaluate("(el, value) => el.value = value", old)
    data = page.locator("form.account-form").evaluate(
        "form => Object.fromEntries(new FormData(form))"
    )
    page.get_by_role("button", name="Record transaction", exact=True).click()
    return data


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
            register(page, base, "actions-browser-alice")
            register(bob, base, "actions-browser-bob")
            portfolio = create(page, base, "Recorded action example")
            record_url, positions_url = portfolio + "transactions/record/", portfolio + "positions/"
            submit(page, record_url, "DEPOSIT", 1, "1000")
            submit(
                page,
                record_url,
                "BUY",
                2,
                quantity="10",
                price="25",
                fees="1",
                security_id="sec_fixture_primary",
            )
            payload = record_action(page, record_url, "SPLIT", 3, new="2", old="1")
            page.get_by_role("heading", name="Transactions", exact=True).wait_for()
            assert "2 for 1" in page.get_by_role("table").inner_text()
            response = owner.request.post(record_url, form=payload)
            assert response.status == 200
            record_action(page, record_url, "DIVIDEND", 4, amount="5")
            page.get_by_role("heading", name="Transactions", exact=True).wait_for()
            submit(
                page,
                record_url,
                "SELL",
                5,
                quantity="8",
                price="15",
                fees="2",
                security_id="sec_fixture_primary",
            )
            page.goto(positions_url)
            assert page.locator(".reference-grid dd").all_text_contents() == [
                "872.00",
                "150.60",
                "17.60",
                "0.00",
                "5.00",
            ]
            assert (
                "12.000000" in page.get_by_role("region", name="Open position table").inner_text()
            )
            # Reject nonrepresentable lot fractions before creating another row.
            record_action(page, record_url, "SPLIT", 6, new="1", old="7")
            assert "cash-in-lieu" in page.locator("main").inner_text()
            for label, width, height in (("desktop", 1280, 900), ("mobile", 390, 844)):
                page.set_viewport_size({"width": width, "height": height})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                page.screenshot(path=f"/tmp/stock-actions-validation-{label}.png", full_page=True)
                page.goto(positions_url)
                assert page.locator(".reference-grid dd").all_text_contents()[-1] == "5.00"
                for name in ("Open position table", "Realized sale table"):
                    region = page.get_by_role("region", name=name)
                    region.focus()
                    assert region.evaluate("el => el === document.activeElement")
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                page.screenshot(path=f"/tmp/stock-actions-positions-{label}.png", full_page=True)
            record_action(page, record_url, "SPLIT", 6, new="1", old="2")
            page.get_by_role("heading", name="Transactions", exact=True).wait_for()
            assert (
                page.locator("tbody tr").count() == 6
            )  # Exact retry/failure inserted no extra rows.
            page.goto(positions_url)
            assert "6.000000" in page.get_by_role("region", name="Open position table").inner_text()
            assert page.locator(".reference-grid dd").all_text_contents()[1] == "150.60"
            response = bob.goto(record_url)
            assert response.status == 404
            assert "Recorded action example" not in bob.locator("main").inner_text()
            response = bob.goto(positions_url)
            assert response.status == 404
            page.get_by_role("button", name="Sign out", exact=True).click()
            page.goto(record_url)
            assert "/sign-in/?next=" in page.url
            assert not errors
            assert all(urlsplit(url).hostname == "127.0.0.1" for url in requests)
            print(
                "Action browser: dividend cash, forward/reverse split, FIFO preservation, "
                "exact retry, fractional rejection, owners and desktop/mobile PASS (synthetic only)"
            )
        finally:
            owner.close()
            other.close()
            browser.close()


if __name__ == "__main__":
    main()
