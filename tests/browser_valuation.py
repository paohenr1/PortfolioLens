"""Explicit as-of valuation workflow; only synthetic prices on an isolated test DB."""

from urllib.parse import urlsplit

from browser_authentication import register
from browser_ledger import fill, submit
from browser_portfolios import create, portfolio_application


def load(page, valuation_url, day):
    page.goto(valuation_url)
    page.get_by_label("Valuation date:", exact=True).fill(day)
    page.locator("#id_share_basis_checked").check()
    page.get_by_role("button", name="Load valuation", exact=True).click()
    page.get_by_role("heading", name="Position values", exact=True).wait_for()


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
            register(page, base, "valuation-browser-alice")
            register(bob, base, "valuation-browser-bob")
            portfolio = create(page, base, "Valuation example")
            page.get_by_role("link", name="View market valuation", exact=True).click()
            valuation_url = page.url
            assert page.locator(".reference-grid").count() == 0
            assert page.get_by_role("region", name="Allocation table", exact=True).count() == 0
            record_url = portfolio + "transactions/record/"
            load(page, valuation_url, "2020-01-08")
            assert "because total value is zero" in page.locator("main").inner_text()
            assert page.get_by_role("region", name="Allocation table").locator(
                "tbody td"
            ).all_text_contents() == ["Recorded cash", "0.00", "Unavailable"]
            submit(page, record_url, "DEPOSIT", 1, "1000")
            load(page, valuation_url, "2020-01-08")
            assert page.get_by_role("region", name="Allocation table").locator(
                "tbody td"
            ).all_text_contents() == ["Recorded cash", "1000.00", "100.00%"]
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
            load(page, valuation_url, "2020-01-08")
            assert page.locator(".reference-grid dd").all_text_contents() == [
                "749.00",
                "251.00",
                "155.00",
                "-96.00",
                "904.00",
            ]
            assert "Confirmed daily close · 2020-01-08" in page.locator("main").inner_text()
            allocation = page.get_by_role("region", name="Allocation table", exact=True)
            assert allocation.locator("tbody tr").count() == 2
            assert allocation.locator("tbody tr td:last-child").all_text_contents() == [
                "82.85%",
                "17.15%",
            ]
            # Later split and dividend must not change a valuation on the older date.
            for kind, sequence in (("SPLIT", 1), ("DIVIDEND", 2)):
                page.goto(record_url)
                fill(
                    page,
                    kind,
                    sequence,
                    "7" if kind == "DIVIDEND" else "",
                    security_id="sec_fixture_primary",
                )
                page.get_by_label("Transaction date:", exact=True).fill("2020-01-09")
                if kind == "SPLIT":
                    page.get_by_label("Split new shares:", exact=True).fill("2")
                    page.get_by_label("Split old shares:", exact=True).fill("1")
                page.get_by_role("button", name="Record transaction", exact=True).click()
                page.get_by_role("heading", name="Transactions", exact=True).wait_for()
            load(page, valuation_url, "2020-01-08")
            assert page.locator(".reference-grid dd").all_text_contents() == [
                "749.00",
                "251.00",
                "155.00",
                "-96.00",
                "904.00",
            ]
            for label, width, height in (("desktop", 1280, 900), ("mobile", 390, 844)):
                page.set_viewport_size({"width": width, "height": height})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                for name in ("Valuation table", "Allocation table"):
                    table = page.get_by_role("region", name=name, exact=True)
                    table.focus()
                    assert table.evaluate("el => el === document.activeElement")
                    page.keyboard.press("ArrowRight")
                page.screenshot(path=f"/tmp/stock-valuation-{label}.png", full_page=True)
                page.get_by_role("region", name="Allocation table").screenshot(
                    path=f"/tmp/stock-allocation-{label}.png"
                )
            # Unconfirmed Jan 9 is rejected even though a raw close is supplied.
            load(page, valuation_url, "2020-01-09")
            assert page.locator(".reference-grid dd").all_text_contents() == [
                "756.00",
                "251.00",
                "Unavailable",
                "Unavailable",
                "Unavailable",
            ]
            assert "Incomplete valuation" in page.locator("main").inner_text()
            assert page.get_by_role("region", name="Allocation table").locator(
                "tbody tr td:last-child"
            ).all_text_contents() == ["Unavailable", "Unavailable"]
            assert "until every position has a usable price" in page.locator("main").inner_text()
            # Empty exact-date observations stay unknown; earlier prices aren't carried forward.
            load(page, valuation_url, "2020-01-11")
            assert "Unavailable" in page.get_by_role("region", name="Valuation table").inner_text()
            response = bob.goto(valuation_url)
            assert response.status == 404
            assert "Valuation example" not in bob.locator("main").inner_text()
            assert "no-store" in response.headers["cache-control"]
            response = owner.request.post(
                valuation_url, form={"as_of": "2020-01-08", "share_basis_checked": "on"}
            )
            assert response.status == 403
            page.get_by_role("button", name="Sign out", exact=True).click()
            page.goto(valuation_url)
            assert "/sign-in/?next=" in page.url
            assert not errors
            assert all(urlsplit(url).hostname == "127.0.0.1" for url in requests)
            print(
                "Valuation browser: exact-date raw close and cash/FIFO totals, later-action "
                "cutoff, unconfirmed/missing prices, CSRF, ownership, desktop/mobile and "
                "keyboard tables, cash-inclusive weights and empty/partial allocations "
                "PASS (synthetic only)"
            )
        finally:
            owner.close()
            other.close()
            browser.close()


if __name__ == "__main__":
    main()
