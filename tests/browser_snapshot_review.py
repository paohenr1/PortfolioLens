"""Synthetic on-demand snapshot review in two real browser sessions."""

from urllib.parse import urlsplit

from browser_authentication import register
from browser_holdings_preview import HEADER, submit
from browser_portfolios import portfolio_application


def create_snapshot(page, base, *, cash_only=False, as_of="2020-01-02"):
    page.goto(base + "/portfolios/check-holdings/")
    submit(
        page, HEADER if cash_only else HEADER + b"TSTF,XNYS,10,USD\n", cash="100.00", as_of=as_of
    )
    page.get_by_role("button", name="Find instrument matches", exact=True).click()
    if not cash_only:
        page.get_by_label("Holding 1: TSTF · XNYS:", exact=True).select_option(
            "sec_fixture_primary"
        )
    page.get_by_role("button", name="Validate selections", exact=True).click()
    page.locator('input[name="confirmed"]').check()
    page.get_by_role("button", name="Save private snapshot", exact=True).click()
    page.get_by_role("link", name="Review snapshot value and concentration", exact=True).click()
    return page.url


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
            register(page, base, "snapshot-review-owner")
            register(bob, base, "snapshot-review-other")
            url = create_snapshot(page, base)
            for label, width, height in (("desktop", 1280, 900), ("mobile", 390, 844)):
                page.set_viewport_size({"width": width, "height": height})
                page.goto(url + "?action=load")
                page.get_by_role("heading", name="No review loaded", exact=True).wait_for()
                page.get_by_role("button", name="Load snapshot review", exact=True).click()
                page.get_by_role(
                    "heading", name="Dated value and input coverage", exact=True
                ).wait_for()
                main = page.locator("main").inner_text()
                for expected in (
                    "205.00",
                    "105.00",
                    "48.78%",
                    "51.22%",
                    "1 of 1",
                    "Confirmed daily raw close",
                ):
                    assert expected in main
                table = page.get_by_role(
                    "region", name="Snapshot valuation and allocation", exact=True
                )
                table.focus()
                assert table.evaluate("el => el === document.activeElement")
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.screenshot(path=f"/tmp/snapshot-review-{label}.png", full_page=True)
                response = bob.goto(url)
                assert response.status == 404
                assert "no-store" in response.headers["cache-control"]
                assert "Synthetic holdings check" not in bob.locator("main").inner_text()
            # This completed date has no fixture observation: do not carry a prior close.
            missing_url = create_snapshot(page, base, as_of="2020-01-13")
            page.get_by_role("button", name="Load snapshot review", exact=True).click()
            assert "0 of 1" in page.locator("main").inner_text()
            assert "No confirmed raw USD close" in page.locator("main").inner_text()
            assert (
                "Totals, weights and concentration are unavailable"
                in page.locator("main").inner_text()
            )
            page.screenshot(path="/tmp/snapshot-review-missing-mobile.png", full_page=True)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.goto(missing_url)
            page.get_by_role("heading", name="No review loaded", exact=True).wait_for()
            create_snapshot(page, base, cash_only=True)
            page.get_by_role("button", name="Load snapshot review", exact=True).click()
            assert "Cash-only snapshot" in page.locator("main").inner_text()
            assert "100.00%" in page.locator("main").inner_text()
            assert "Not applicable" in page.locator("main").inner_text()
            page.get_by_role("button", name="Sign out", exact=True).click()
            page.goto(url)
            assert "/sign-in/?next=" in page.url
            assert not errors
            assert all(urlsplit(url).hostname == "127.0.0.1" for url in requests)
            print(
                "Snapshot review browser PASS: exact dated values, reconciled allocation, "
                "concentration, explicit loads, two-user isolation, missing prices, cash-only, "
                "keyboard tables and desktop/mobile; synthetic local fixtures only."
            )
        finally:
            owner.close()
            other.close()
            browser.close()


if __name__ == "__main__":
    main()
