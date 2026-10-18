"""Synthetic holdings CSV checks in an isolated two-user browser database."""

from urllib.parse import urlsplit

from browser_authentication import register
from browser_portfolios import portfolio_application

HEADER = b"ticker,exchange_mic,quantity,currency\n"
VALID = HEADER + b"TSTF,XNAS,0.000001,USD\nTST-B,XNYS,2.500000,USD\n"


def submit(page, data=VALID, cash="100.00", as_of="2020-01-02"):
    page.get_by_label("Snapshot name:", exact=True).fill("Synthetic holdings check")
    page.get_by_label("Holdings as-of date:", exact=True).fill(as_of)
    page.get_by_label("Cash balance (USD):", exact=True).fill(cash)
    page.get_by_label("Holdings CSV:", exact=True).set_input_files(
        {"name": "synthetic.csv", "mimeType": "text/csv", "buffer": data}
    )
    page.get_by_role("button", name="Check CSV", exact=True).click()


def main():
    from playwright.sync_api import sync_playwright

    with portfolio_application() as base, sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path="/usr/bin/chromium", headless=True)
        owner, other = browser.new_context(), browser.new_context()
        errors, requests = [], []
        try:
            for context in (owner, other):
                context.on("request", lambda request: requests.append(request.url))
            page, bob = owner.new_page(), other.new_page()
            for current in (page, bob):
                current.on("pageerror", lambda error: errors.append(str(error)))
            register(page, base, "holdings-browser-owner")
            register(bob, base, "holdings-browser-other")
            page.goto(base + "/portfolios/")
            page.get_by_role("link", name="Check a holdings CSV", exact=True).click()
            url = page.url
            for name, width, height in (("desktop", 1280, 900), ("mobile", 390, 844)):
                page.set_viewport_size({"width": width, "height": height})
                page.goto(url)
                submit(page)
                page.get_by_role("heading", name="Input preview — not saved", exact=True).wait_for()
                assert page.locator("tbody tr").count() == 2
                assert (
                    page.locator("tbody tr").first.locator("td").nth(3).inner_text() == "0.000001"
                )
                # The scroll container is keyboard focusable even without implicit region semantics.
                table = page.locator('[aria-label="Supplied holdings"]')
                table.focus()
                assert table.evaluate("el => el === document.activeElement")
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.screenshot(path=f"/tmp/holdings-preview-{name}.png", full_page=True)
                submit(page, VALID + b"TSTF,XNAS,1,USD\n")
                page.get_by_role("heading", name="CSV errors", exact=True).wait_for()
                assert "Duplicate holding" in page.locator("main").inner_text()
                assert (
                    page.get_by_role(
                        "heading", name="Input preview — not saved", exact=True
                    ).count()
                    == 0
                )
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                submit(page, HEADER, cash="0.01")
                assert "Cash-only input" in page.locator("main").inner_text()
                page.goto(url)
                assert page.locator("#id_name").input_value() == ""
            bob.goto(url)
            assert bob.locator("#id_name").input_value() == ""
            assert "Synthetic holdings check" not in bob.locator("main").inner_text()
            page.get_by_role("button", name="Sign out", exact=True).click()
            page.goto(url)
            assert "/sign-in/?next=" in page.url
            assert not errors
            assert all(urlsplit(url).hostname == "127.0.0.1" for url in requests)
            print(
                "Holdings CSV browser PASS: exact preview, duplicate errors, cash-only, "
                "private reload, "
                "sign-out, keyboard table and desktop/mobile; synthetic local inputs only."
            )
        finally:
            owner.close()
            other.close()
            browser.close()


if __name__ == "__main__":
    main()
