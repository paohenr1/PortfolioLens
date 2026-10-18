"""Two users import and delete synthetic holdings in a disposable PostgreSQL DB."""

from urllib.parse import urlsplit

from browser_authentication import register
from browser_holdings_preview import HEADER, submit
from browser_portfolios import portfolio_application


def main():
    from playwright.sync_api import sync_playwright

    with portfolio_application(ledger_fixtures=True) as base, sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path="/usr/bin/chromium", headless=True)
        owner, other = browser.new_context(), browser.new_context()
        errors, requests = [], []
        try:
            for context in (owner, other):
                context.on("request", lambda request: requests.append(request.url))
            page, bob = owner.new_page(), other.new_page()
            for current in (page, bob):
                current.on("pageerror", lambda error: errors.append(str(error)))
            register(page, base, "snapshot-browser-owner")
            register(bob, base, "snapshot-browser-other")
            for label, width, height in (("desktop", 1280, 900), ("mobile", 390, 844)):
                page.set_viewport_size({"width": width, "height": height})
                page.goto(base + "/portfolios/")
                page.get_by_role("link", name="My holdings snapshots", exact=True).click()
                page.get_by_role("link", name="Import a holdings CSV", exact=True).click()
                submit(page, HEADER + b"TSTF,XNYS,0.000001,USD\n", cash="100.01")
                page.get_by_role("button", name="Find instrument matches", exact=True).click()
                page.get_by_role("heading", name="Choose instrument matches", exact=True).wait_for()
                select = page.get_by_label("Holding 1: TSTF · XNYS:", exact=True)
                assert select.input_value() == ""
                select.select_option("sec_fixture_primary")
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.screenshot(path=f"/tmp/snapshot-matches-{label}.png", full_page=True)
                page.get_by_role("button", name="Validate selections", exact=True).click()
                page.get_by_role("heading", name="Confirm snapshot inputs", exact=True).wait_for()
                assert (
                    page.locator("tbody tr").first.locator("td").nth(2).inner_text() == "0.000001"
                )
                assert "sec_fixture_primary" in page.locator("main").inner_text()
                page.locator('input[name="confirmed"]').check()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.screenshot(path=f"/tmp/snapshot-confirm-{label}.png", full_page=True)
                page.get_by_role("button", name="Save private snapshot", exact=True).click()
                page.get_by_role("heading", name="Synthetic holdings check", exact=True).wait_for()
                saved_url = page.url
                assert "USD 100.01" in page.locator("main").inner_text()
                assert "0.000001" in page.locator("main").inner_text()
                assert (
                    "Pricing and snapshot analysis are not available yet"
                    in page.locator("main").inner_text()
                )
                page.locator('[aria-label="Saved snapshot holdings"]').focus()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.screenshot(path=f"/tmp/snapshot-saved-{label}.png", full_page=True)
                page.reload()
                page.get_by_role("heading", name="Synthetic holdings check", exact=True).wait_for()
                response = bob.goto(saved_url)
                assert response.status == 404
                assert "no-store" in response.headers["cache-control"]
                bob.goto(base + "/portfolios/snapshots/")
                assert "Synthetic holdings check" not in bob.locator("main").inner_text()
                page.get_by_role("link", name="Delete this snapshot", exact=True).click()
                page.get_by_role("link", name="Keep snapshot", exact=True).click()
                page.get_by_role("heading", name="Synthetic holdings check", exact=True).wait_for()
                page.get_by_role("link", name="Delete this snapshot", exact=True).click()
                page.get_by_label("Delete this snapshot and its holdings.").check()
                page.get_by_role("button", name="Delete snapshot", exact=True).click()
                assert "No saved holdings snapshots yet" in page.locator("main").inner_text()
                assert page.goto(saved_url).status == 404
            # Cash-only imports need no provider identity and retain explicit cents.
            page.goto(base + "/portfolios/check-holdings/")
            submit(page, HEADER, cash="0.01")
            page.get_by_role("button", name="Find instrument matches", exact=True).click()
            page.get_by_role("button", name="Validate selections", exact=True).click()
            page.locator('input[name="confirmed"]').check()
            page.get_by_role("button", name="Save private snapshot", exact=True).click()
            assert "Cash-only snapshot" in page.locator("main").inner_text()
            assert "USD 0.01" in page.locator("main").inner_text()
            page.get_by_role("button", name="Sign out", exact=True).click()
            page.goto(base + "/portfolios/snapshots/")
            assert "/sign-in/?next=" in page.url
            assert not errors
            assert all(urlsplit(url).hostname == "127.0.0.1" for url in requests)
            print(
                "Snapshot browser PASS: explicit resolution, exact quantities, confirmation, "
                "private save/reload, two-user isolation, deletion, cash-only, keyboard tables "
                "and desktop/mobile; synthetic local fixtures only."
            )
        finally:
            owner.close()
            other.close()
            browser.close()


if __name__ == "__main__":
    main()
