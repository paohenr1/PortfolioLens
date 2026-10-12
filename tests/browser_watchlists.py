"""Two real browser users manage private watchlists in an isolated fixture database."""

from urllib.parse import urlsplit

from browser_authentication import register
from browser_portfolios import portfolio_application


def create(page, base, name):
    page.goto(base + "/watchlists/")
    page.get_by_role("link", name="Create watchlist", exact=True).click()
    page.get_by_label("Watchlist name:", exact=True).fill(name)
    page.get_by_role("button", name="Create watchlist", exact=True).click()
    page.get_by_role("heading", name=name, exact=True).wait_for()
    return page.url


def main():
    from playwright.sync_api import sync_playwright

    with portfolio_application(ledger_fixtures=True) as base, sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path="/usr/bin/chromium", headless=True)
        contexts, requests, errors = [], [], []
        try:
            for width, height in ((1280, 900), (390, 844)):
                context = browser.new_context(viewport={"width": width, "height": height})
                contexts.append(context)
                context.on("request", lambda request: requests.append(request.url))
            alice, bob = [context.new_page() for context in contexts]
            for page in (alice, bob):
                page.on("pageerror", lambda error: errors.append(str(error)))
            alice.goto(base + "/watchlists/")
            assert "/sign-in/?next=" in alice.url
            register(alice, base, "watchlist-browser-alice")
            register(bob, base, "watchlist-browser-bob")
            for page in (alice, bob):
                page.goto(base + "/watchlists/")
                assert page.get_by_role("heading", name="No watchlists yet").is_visible()
            alice_url = create(alice, base, "Income candidates")
            bob_url = create(bob, base, "Private research")
            for page, foreign_url, foreign_name in (
                (alice, bob_url, "Private research"),
                (bob, alice_url, "Income candidates"),
            ):
                response = page.goto(foreign_url)
                assert response.status == 404
                assert "no-store" in response.headers["cache-control"]
                assert foreign_name not in page.locator("main").inner_text()

            for label, page, own_url, own_name, foreign_name in (
                ("desktop", alice, alice_url, "Income candidates", "Private research"),
                ("mobile", bob, bob_url, "Private research", "Income candidates"),
            ):
                page.goto(base + "/stocks/sec_fixture_primary/")
                page.get_by_role("link", name="Add to watchlist", exact=True).focus()
                page.keyboard.press("Enter")
                assert (
                    page.get_by_label("Provider instrument ID:", exact=True).input_value()
                    == "sec_fixture_primary"
                )
                assert foreign_name not in page.locator("main").inner_text()
                page.get_by_label("Watchlist:", exact=True).select_option(label=own_name)
                page.get_by_role("button", name="Add instrument", exact=True).click()
                page.get_by_role("heading", name=own_name, exact=True).wait_for()
                assert page.url == own_url
                assert page.locator("tbody tr").count() == 1
                assert "Fixture Research Corp" in page.locator("tbody").inner_text()
                assert "XNYS · USD" in page.locator("tbody").inner_text()
                assert "saved Intrinio references" in page.locator("main").inner_text()
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                page.get_by_role("region", name="Saved instrument table").focus()
                page.screenshot(path=f"/tmp/stock-watchlists-detail-{label}.png", full_page=True)
                page.get_by_role("link", name="Add instrument", exact=True).click()
                page.get_by_label("Provider instrument ID:", exact=True).fill("sec_fixture_primary")
                page.get_by_role("button", name="Add instrument", exact=True).click()
                page.get_by_role("heading", name=own_name, exact=True).wait_for()
                assert page.locator("tbody tr").count() == 1
                page.get_by_role("link", name="Remove TSTF", exact=True).click()
                remove_url = page.url
                assert "Remove TSTF from" in page.locator("main").inner_text()
                assert page.context.request.post(remove_url).status == 403
                page.get_by_role("link", name="Keep instrument", exact=True).click()
                assert page.locator("tbody tr").count() == 1
                page.get_by_role("link", name="Remove TSTF", exact=True).click()
                page.get_by_role("button", name="Remove instrument", exact=True).click()
                page.get_by_role("heading", name="No instruments yet", exact=True).wait_for()
                assert page.url == own_url
                page.screenshot(path=f"/tmp/stock-watchlists-empty-{label}.png", full_page=True)

            alice.goto(alice_url + "add/")
            alice.get_by_label("Provider instrument ID:", exact=True).fill("sec_fixture_missing")
            alice.get_by_role("button", name="Add instrument", exact=True).click()
            assert "This instrument was not found" in alice.locator("main").inner_text()
            assert (
                alice.get_by_label("Provider instrument ID:", exact=True).input_value()
                == "sec_fixture_missing"
            )
            token = alice.locator('main [name="csrfmiddlewaretoken"]').input_value()
            forged = alice.context.request.post(
                bob_url + "add/",
                form={
                    "csrfmiddlewaretoken": token,
                    "security_id": "sec_fixture_primary",
                },
            )
            assert forged.status == 404
            assert "no-store" in forged.headers["cache-control"]
            assert "Private research" not in forged.text()
            alice.goto(base + "/watchlists/create/")
            alice.get_by_label("Watchlist name:", exact=True).fill(" INCOME CANDIDATES ")
            alice.get_by_role("button", name="Create watchlist", exact=True).click()
            assert (
                "You already have a watchlist with this name." in alice.locator("main").inner_text()
            )
            bob.goto(bob_url)
            bob.get_by_role("button", name="Sign out", exact=True).click()
            bob.goto(bob_url)
            assert "/sign-in/?next=" in bob.url
            assert not errors
            assert all(urlsplit(url).hostname == "127.0.0.1" for url in requests)
            print(
                "Watchlist browser workflow: desktop/mobile, keyboard, two-user isolation, "
                "instrument selection, duplicate add, confirmation/remove, CSRF, provider error, "
                "forged owner and sign-out PASS"
            )
        finally:
            for context in contexts:
                context.close()
            browser.close()


if __name__ == "__main__":
    main()
