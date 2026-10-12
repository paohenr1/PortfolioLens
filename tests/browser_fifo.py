"""Synthetic journal trades; actual private FIFO pages in a disposable PostgreSQL DB."""

from urllib.parse import urlsplit

from browser_authentication import register
from browser_ledger import submit
from browser_portfolios import create, portfolio_application


def main():
    from playwright.sync_api import sync_playwright

    with portfolio_application(ledger_fixtures=True) as base, sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path="/usr/bin/chromium", headless=True)
        owner = browser.new_context(viewport={"width": 1280, "height": 900})
        other = browser.new_context(viewport={"width": 390, "height": 844})
        errors, requests = [], []
        try:
            page, bob = owner.new_page(), other.new_page()
            for session in (owner, other):
                session.on("request", lambda request: requests.append(request.url))
            for current in (page, bob):
                current.on("pageerror", lambda error: errors.append(str(error)))
            register(page, base, "fifo-browser-alice")
            register(bob, base, "fifo-browser-bob")
            portfolio = create(page, base, "FIFO example")
            page.get_by_role("link", name="View positions and gains", exact=True).click()
            positions_url = page.url
            assert "No open positions" in page.locator("main").inner_text()
            assert "No sales recorded" in page.locator("main").inner_text()
            record_url = portfolio + "transactions/record/"
            submit(page, record_url, "DEPOSIT", 1, "1000")
            for kind, quantity, price, fees, sequence in (
                ("BUY", "3", "10", "1", 2),
                ("BUY", "2", "20", "2", 3),
                ("SELL", "4", "30", "3", 4),
            ):
                submit(
                    page,
                    record_url,
                    kind,
                    sequence,
                    quantity=quantity,
                    price=price,
                    fees=fees,
                    security_id="sec_fixture_primary",
                )
            page.get_by_role("link", name="View positions and gains", exact=True).click()
            assert page.url == positions_url
            totals = page.locator(".reference-grid")
            assert totals.locator("dd").all_text_contents() == [
                "1044.00",
                "21.00",
                "65.00",
                "0.00",
                "0.00",
            ]
            positions = page.get_by_role("region", name="Open position table", exact=True)
            sales = page.get_by_role("region", name="Realized sale table", exact=True)
            assert positions.locator("tbody tr").count() == sales.locator("tbody tr").count() == 1
            assert "1.000000" in positions.inner_text()
            sale_cells = sales.locator("tbody td").all_text_contents()
            assert sale_cells[2:8] == ["4.000000", "120.00", "3.00", "117.00", "52.00", "65.00"]
            sales.get_by_text("2 lots", exact=True).click()
            assert "order 2: 3.000000 shares; 31.00 USD allocated cost" in sales.inner_text()
            assert "order 3: 1.000000 shares; 21.00 USD allocated cost" in sales.inner_text()
            positions.get_by_text("1 open lot", exact=True).click()
            assert "order 3: 1.000000 shares; 21.00 USD remaining cost" in positions.inner_text()
            for label, width, height in (("desktop", 1280, 900), ("mobile", 390, 844)):
                page.set_viewport_size({"width": width, "height": height})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                for table in (positions, sales):
                    table.focus()
                    assert table.evaluate("el => el === document.activeElement")
                    page.keyboard.press("ArrowRight")
                assert "First in, first out" in page.locator("main").inner_text()
                assert (
                    "Money-weighted returns remain unavailable" in page.locator("main").inner_text()
                )
                page.screenshot(path=f"/tmp/stock-fifo-{label}.png", full_page=True)
            response = bob.goto(positions_url)
            assert response.status == 404
            assert "FIFO example" not in bob.locator("main").inner_text()
            # Close the remaining lot at a loss and keep both realized sales visible.
            submit(
                page,
                record_url,
                "SELL",
                5,
                quantity="1",
                price="10",
                fees="1",
                security_id="sec_fixture_primary",
            )
            page.goto(positions_url)
            assert "No open positions" in page.locator("main").inner_text()
            assert page.locator(".reference-grid dd").all_text_contents() == [
                "1053.00",
                "0.00",
                "53.00",
                "0.00",
                "0.00",
            ]
            assert "-12.00" in page.get_by_role("region", name="Realized sale table").inner_text()
            page.get_by_role("button", name="Sign out", exact=True).click()
            page.goto(positions_url)
            assert "/sign-in/?next=" in page.url
            assert not errors
            assert all(urlsplit(url).hostname == "127.0.0.1" for url in requests)
            print(
                "FIFO browser: multi-lot basis/gain, lot provenance, final loss/close, "
                "owner isolation, desktop/mobile and keyboard tables PASS (synthetic only)"
            )
        finally:
            owner.close()
            other.close()
            browser.close()


if __name__ == "__main__":
    main()
