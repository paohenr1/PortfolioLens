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


def verify_print(page, label, requests):
    """Print the existing DOM: no navigation, form submission or resource reload."""
    button = page.get_by_role("button", name="Print / save PDF", exact=True)
    button.wait_for(state="visible")
    before, url = len(requests), page.url
    page.evaluate("""() => {
        window.originalPrint = window.print;
        window.printCalls = 0;
        window.print = () => { window.printCalls += 1; };
    }""")
    button.focus()
    page.keyboard.press("Enter")
    assert page.evaluate("window.printCalls") == 1
    page.evaluate("window.print = window.originalPrint")
    assert page.url == url and len(requests) == before
    page.emulate_media(media="print")
    assert not button.is_visible()
    assert not page.locator(".header").is_visible()
    assert not page.get_by_role("button", name="Load snapshot review", exact=True).is_visible()
    assert page.get_by_role("heading", name="Input basis and limitations", exact=True).is_visible()
    assert page.locator(".review-load-time").is_visible()
    assert page.locator(".price-table").evaluate("el => el.scrollWidth <= el.clientWidth + 1")
    page.pdf(path=f"/tmp/snapshot-print-{label}.pdf", prefer_css_page_size=True)
    assert len(requests) == before and page.url == url
    page.emulate_media(media="screen")


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
                assert page.get_by_role("button", name="Print / save PDF", exact=True).count() == 0
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
                verify_print(page, label, requests)
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
            verify_print(page, "incomplete", requests)
            page.goto(missing_url)
            page.get_by_role("heading", name="No review loaded", exact=True).wait_for()
            create_snapshot(page, base, cash_only=True)
            page.get_by_role("button", name="Load snapshot review", exact=True).click()
            assert "Cash-only snapshot" in page.locator("main").inner_text()
            assert "100.00%" in page.locator("main").inner_text()
            assert "Not applicable" in page.locator("main").inner_text()
            verify_print(page, "cash-only", requests)
            page.get_by_role("button", name="Sign out", exact=True).click()
            page.goto(url)
            assert "/sign-in/?next=" in page.url
            assert not errors
            assert all(urlsplit(url).hostname == "127.0.0.1" for url in requests)
            print(
                "Snapshot review browser PASS: exact dated values, reconciled allocation, "
                "concentration, explicit loads, two-user isolation, missing prices, cash-only, "
                "keyboard tables, desktop/mobile and request-free browser PDF printing; "
                "synthetic local fixtures only."
            )
        finally:
            owner.close()
            other.close()
            browser.close()


if __name__ == "__main__":
    main()
