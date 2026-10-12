"""One continuous synthetic account/ledger/returns/watchlist release acceptance."""

import argparse
import time
from urllib.parse import urlsplit

from browser_acceptance import RequestPacer, responsive
from browser_actions import record_action
from browser_authentication import NEW_PASSWORD, PASSWORD, register
from browser_daily_returns import load as load_daily
from browser_ledger import fill, submit
from browser_performance import load as load_performance
from browser_portfolios import create, portfolio_application
from browser_valuation import load as load_valuation
from browser_watchlists import create as create_watchlist


def main():
    from playwright.sync_api import sync_playwright

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shared-limits", action="store_true")
    shared = parser.parse_args().shared_limits
    with (
        portfolio_application(
            ledger_fixtures=True, rate_limit_backend="postgresql" if shared else "memory"
        ) as base,
        sync_playwright() as driver,
    ):
        browser = driver.chromium.launch(executable_path="/usr/bin/chromium", headless=True)
        owner, other = browser.new_context(), browser.new_context()
        errors, requests = [], []
        pacer = RequestPacer(clock=time.time if shared else time.monotonic)
        try:
            page, bob = owner.new_page(), other.new_page()
            for context in (owner, other):
                context.on("request", lambda r: requests.append(r.url))
            for current in (page, bob):
                current.on("pageerror", lambda e: errors.append(str(e)))
            register(page, base, "release-journey-owner")
            register(bob, base, "release-journey-other")
            portfolio = create(page, base, "Release journey")
            record, journal = portfolio + "transactions/record/", portfolio + "transactions/"
            submit(page, record, "DEPOSIT", 1, "1000")
            pacer.before(1)
            page.goto(record)
            fill(
                page,
                "BUY",
                2,
                quantity="10",
                price="10",
                fees="1",
                security_id="sec_fixture_primary",
            )
            retry = page.locator("form.account-form").evaluate(
                "f=>Object.fromEntries(new FormData(f))"
            )
            page.get_by_role("button", name="Record transaction", exact=True).click()
            page.get_by_role("heading", name="Transactions", exact=True).wait_for()
            assert "Recorded cash: 899.00 USD" in page.locator("main").inner_text()
            assert owner.request.post(record, form=retry).status == 200
            page.goto(journal)
            assert page.locator("tbody tr").count() == 2
            pacer.before(1)
            record_action(page, record, "DIVIDEND", 3, amount="5")
            pacer.before(1)
            record_action(page, record, "SPLIT", 4, new="2", old="1")
            pacer.before(1)
            submit(
                page,
                record,
                "SELL",
                5,
                quantity="4",
                price="8",
                fees="1",
                security_id="sec_fixture_primary",
            )
            submit(page, record, "FEE", 6, "2")
            fee = page.locator("tbody tr").filter(
                has=page.get_by_role("cell", name="Fee", exact=True)
            )
            fee.get_by_role("link", name="Correct", exact=True).click()
            correction_url = page.url
            page.get_by_label("Cash amount (USD):", exact=True).fill("3")
            page.get_by_label("Correction reason:", exact=True).fill(
                "Independent release fee example"
            )
            page.get_by_role("button", name="Preview correction", exact=True).click()
            preview = page.get_by_role("region", name="Correction accounting preview")
            assert "933.00" in preview.inner_text() and "932.00" in preview.inner_text()
            assert owner.request.post(correction_url, form={"stage": "save"}).status == 403
            page.get_by_label(
                "I reviewed this correction and its effect on the journal.", exact=True
            ).check()
            page.get_by_role("button", name="Save correction", exact=True).click()
            page.get_by_role("heading", name="Correction history", exact=True).wait_for()
            assert "Original entry" in page.locator("main").inner_text()
            assert "Replacement entry" in page.locator("main").inner_text()
            audit = page.url
            submit(page, record, "WITHDRAWAL", 7, "100")
            assert "Recorded cash: 832.00 USD" in page.locator("main").inner_text()
            page.goto(portfolio + "positions/")
            assert page.locator(".reference-grid dd").all_text_contents() == [
                "832.00",
                "80.80",
                "10.80",
                "3.00",
                "5.00",
            ]
            assert (
                "16.000000" in page.get_by_role("region", name="Open position table").inner_text()
            )
            responsive(page, screenshots=True, name="release-journey-fifo")
            page.goto(record)
            fill(page, "DEPOSIT", 1, "50")
            page.get_by_label("Transaction date:", exact=True).fill("2020-01-06")
            page.get_by_role("button", name="Record transaction", exact=True).click()
            page.get_by_role("heading", name="Transactions", exact=True).wait_for()
            pacer.before(3)
            load_performance(page, portfolio + "performance/")
            assert page.locator(".reference-grid dd").all_text_contents() == ["7.8165%"]
            responsive(page, screenshots=True, name="release-journey-performance")
            pacer.before(1)
            load_daily(page, portfolio + "daily-returns/")
            assert page.locator(".reference-grid:not(.risk-summary) dd").all_text_contents() == [
                "7.8165%"
            ]
            assert (
                page.get_by_role("region", name="Daily return table").locator("tbody tr").count()
                == 4
            )
            responsive(page, screenshots=True, name="release-journey-daily")
            pacer.before(1)
            load_valuation(page, portfolio + "valuation/", "2020-01-08")
            text = page.locator("main").inner_text()
            for expected in ("882.00", "80.80", "248.00", "1130.00", "167.20", "78.05", "21.95"):
                assert expected in text
            responsive(page, screenshots=True, name="release-journey-valuation")
            watchlist = create_watchlist(page, base, "Release watchlist")
            page.get_by_role("link", name="Add instrument", exact=True).click()
            page.get_by_label("Provider instrument ID:", exact=True).fill("sec_fixture_primary")
            pacer.before(1)
            page.get_by_role("button", name="Add instrument", exact=True).click()
            page.get_by_role("link", name="Edit saved preferences", exact=True).click()
            page.get_by_label("Default price basis:", exact=True).select_option("adjusted")
            page.get_by_label("Default volume basis:", exact=True).select_option("raw")
            page.get_by_label("Instrument order:", exact=True).select_option("ticker")
            page.get_by_role("button", name="Save preferences", exact=True).click()
            page.get_by_role("link", name="View daily market information", exact=True).click()
            assert page.get_by_label("Price basis", exact=True).input_value() == "adjusted"
            page.get_by_label("Daily observation date", exact=True).fill("2020-01-08")
            page.locator('.watchlist-picker input[type="checkbox"]').check()
            pacer.before(1)
            page.get_by_role("button", name="Load selected market information").click()
            assert page.locator(".market-close").inner_text() == "14.5 USD per share"
            assert page.locator(".market-volume").inner_text() == "Unavailable"
            responsive(page, screenshots=True, name="release-journey-watchlist")
            for url in (
                journal,
                portfolio + "positions/",
                portfolio + "valuation/",
                portfolio + "performance/",
                portfolio + "daily-returns/",
                audit,
                watchlist,
                watchlist + "preferences/",
                watchlist + "market/",
            ):
                response = bob.goto(url)
                assert response.status == 404
                assert "no-store" in response.headers["cache-control"]
                assert "Release journey" not in bob.locator("main").inner_text()
            page.goto(base + "/password/change/")
            page.get_by_label("Old password:", exact=True).fill(PASSWORD)
            page.get_by_label("New password:", exact=True).fill(NEW_PASSWORD)
            page.get_by_label("New password confirmation:", exact=True).fill(NEW_PASSWORD)
            page.get_by_role("button", name="Change password", exact=True).click()
            assert "/password/changed/" in page.url
            page.get_by_role("button", name="Sign out", exact=True).click()
            page.goto(portfolio)
            assert "/sign-in/?next=" in page.url
            page.get_by_label("Username:", exact=True).fill("release-journey-owner")
            page.get_by_label("Password:", exact=True).fill(NEW_PASSWORD)
            page.get_by_role("button", name="Sign in", exact=True).click()
            page.get_by_role("heading", name="Release journey", exact=True).wait_for()
            assert not errors, errors
            assert all(urlsplit(url).hostname == "127.0.0.1" for url in requests)
            print(
                "Continuous synthetic release journey PASS: account, idempotent trade, actions, "
                "correction/audit, FIFO, EOD funding, valuation/allocation, matched TWR/daily "
                "return, saved watchlist preferences, two-owner isolation, CSRF, password "
                "change and sign-in. Disposable PostgreSQL only."
            )
            print(f"Admission backend verified: {'postgresql' if shared else 'memory'}.")
        finally:
            owner.close()
            other.close()
            browser.close()


if __name__ == "__main__":
    main()
