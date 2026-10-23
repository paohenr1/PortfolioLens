"""Two real browser users create private portfolios in a disposable PostgreSQL DB."""

import os
import select
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from browser_authentication import register

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.development_database import database_environment  # noqa: E402


@contextmanager
def portfolio_application(
    *,
    ledger_fixtures=False,
    watchlist_market_fixtures=False,
    live_market_data=False,
    max_live_requests=32,
    live_request_counts=None,
    rate_limit_backend="memory",
):
    if live_market_data and (ledger_fixtures or watchlist_market_fixtures):
        raise ValueError("Live acceptance cannot enable a synthetic provider transport.")
    if type(max_live_requests) is not int or not 1 <= max_live_requests <= 32:
        raise ValueError("Live acceptance requires a request cap from 1 through 32.")
    if rate_limit_backend not in {"memory", "postgresql"}:
        raise ValueError("Unsupported browser admission backend.")
    root = Path(__file__).resolve().parent.parent
    with Path("/tmp/stock-portfolio-server.log").open("a") as diagnostics:
        process = subprocess.Popen(
            [
                str(root / ".venv/bin/python"),
                str(root / "tests/portfolio_server.py"),
            ],
            cwd=root,
            env={
                **os.environ,
                **database_environment("stock_research_test", "stock_research_tests"),
                "DJANGO_RATE_LIMIT_BACKEND": rate_limit_backend,
                "STOCK_LEDGER_BROWSER_FIXTURES": "1" if ledger_fixtures else "0",
                "STOCK_WATCHLIST_MARKET_BROWSER_FIXTURES": "1"
                if watchlist_market_fixtures
                else "0",
                "STOCK_MARKET_BROWSER_LIVE": "1" if live_market_data else "0",
                "STOCK_MARKET_BROWSER_MAX_REQUESTS": str(max_live_requests),
            },
            stdout=subprocess.PIPE,
            stderr=diagnostics,
            text=True,
        )
        try:
            if not select.select([process.stdout], [], [], 15)[0]:
                raise RuntimeError("The isolated PostgreSQL portfolio server did not start.")
            port = int(process.stdout.readline().strip())
            yield f"http://127.0.0.1:{port}"
        finally:
            # Signal the actual Python child so its finally block removes its DB.
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
                raise RuntimeError(
                    "Portfolio browser server did not cleanly stop; verify test DB cleanup."
                ) from None
            if process.returncode not in (0, -15):
                raise RuntimeError("Portfolio server shutdown failed; inspect test diagnostics.")
            if live_market_data:
                import json

                report = json.loads(process.stdout.read().strip())
                if live_request_counts is not None:
                    live_request_counts.append(report["live_request_count"])


def create(page, base, name):
    page.goto(base + "/portfolios/")
    page.get_by_role("link", name="Create portfolio", exact=True).click()
    page.get_by_label("Portfolio name:", exact=True).fill(name)
    page.get_by_label("Reporting currency:", exact=True).select_option("USD")
    page.get_by_role("button", name="Create portfolio", exact=True).click()
    page.get_by_role("heading", name=name, exact=True).wait_for()
    assert page.get_by_role("button", name="Update valuation & performance").is_visible()
    return page.url


def main():
    from playwright.sync_api import sync_playwright

    with portfolio_application() as base, sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path="/usr/bin/chromium", headless=True)
        contexts = []
        errors, requests = [], []
        try:
            for width, height in ((1280, 900), (390, 844)):
                context = browser.new_context(viewport={"width": width, "height": height})
                contexts.append(context)
                context.on("request", lambda request: requests.append(request.url))
            alice, bob = [context.new_page() for context in contexts]
            for page in (alice, bob):
                page.on("pageerror", lambda error: errors.append(str(error)))
            alice.goto(base + "/portfolios/")
            assert "/sign-in/?next=" in alice.url
            register(alice, base, "portfolio-browser-alice")
            register(bob, base, "portfolio-browser-bob")
            for page in (alice, bob):
                page.goto(base + "/portfolios/")
                assert page.get_by_role("heading", name="No portfolios yet").is_visible()
            alice_url = create(alice, base, "Long-term retirement")
            bob_url = create(bob, base, "Private savings")
            response = bob.goto(alice_url)
            assert response.status == 404
            assert "no-store" in response.headers["cache-control"]
            assert "Long-term retirement" not in bob.locator("main").inner_text()
            response = alice.goto(bob_url)
            assert response.status == 404
            assert "Private savings" not in alice.locator("main").inner_text()

            for name, page, own_url, own_name, foreign_name in (
                ("desktop", alice, alice_url, "Long-term retirement", "Private savings"),
                ("mobile", bob, bob_url, "Private savings", "Long-term retirement"),
            ):
                page.goto(base + "/portfolios/?owner=999999")
                assert page.get_by_role("link", name=own_name, exact=True).is_visible()
                assert foreign_name not in page.locator("main").inner_text()
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                page.screenshot(path=f"/tmp/stock-portfolios-list-{name}.png", full_page=True)
                page.get_by_role("link", name=own_name, exact=True).focus()
                page.keyboard.press("Enter")
                page.get_by_role("heading", name=own_name, exact=True).wait_for()
                assert page.url == own_url
                page.get_by_role("navigation", name="Main navigation").get_by_role(
                    "link", name="My Portfolio", exact=True
                ).click()
                page.get_by_role("heading", name=own_name, exact=True).wait_for()
                assert page.url == own_url
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                page.screenshot(path=f"/tmp/stock-portfolios-detail-{name}.png", full_page=True)
                page.goto(base + "/portfolios/create/")
                page.get_by_label("Portfolio name:", exact=True).fill(
                    "  " + own_name.upper() + "  "
                )
                page.get_by_label("Reporting currency:", exact=True).select_option("USD")
                page.get_by_role("button", name="Create portfolio", exact=True).click()
                assert (
                    "You already have a portfolio with this name."
                    in page.locator("main").inner_text()
                )
                assert (
                    page.get_by_label("Portfolio name:", exact=True).get_attribute("aria-invalid")
                    == "true"
                )
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                page.screenshot(path=f"/tmp/stock-portfolios-duplicate-{name}.png", full_page=True)
            bob.get_by_role("button", name="Sign out", exact=True).click()
            bob.goto(bob_url)
            assert "/sign-in/?next=" in bob.url
            assert not errors
            assert all(urlsplit(url).hostname == "127.0.0.1" for url in requests)
            assert not any("intrinio" in url or "/stocks/" in url for url in requests)
            print(
                "PostgreSQL browser workflow: create/list/detail, two-user isolation, "
                "duplicate validation, sign-out, desktop/mobile and keyboard controls PASS"
            )
        finally:
            for context in contexts:
                context.close()
            browser.close()


if __name__ == "__main__":
    main()
