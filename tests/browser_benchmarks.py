"""Synthetic benchmark returns and chart interaction on a disposable PostgreSQL DB."""

from urllib.parse import urlsplit

from browser_authentication import register
from browser_ledger import fill, submit
from browser_portfolios import create, portfolio_application


def load(page, url, end="2020-01-08"):
    page.goto(url)
    page.locator("#id_start_date").fill("2020-01-02")
    page.locator("#id_end_date").fill(end)
    page.locator("#id_timing_checked").check()
    page.locator("#id_benchmark_id").fill("sec_fixture_benchmark")
    page.get_by_role("button", name="Load daily returns", exact=True).click()


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
            register(page, base, "benchmark-browser-alice")
            register(bob, base, "benchmark-browser-bob")
            portfolio = create(page, base, "Benchmark example")
            url, record_url = portfolio + "daily-returns/", portfolio + "transactions/record/"
            page.goto(url)
            assert page.locator(".benchmark-summary").count() == 0
            submit(page, record_url, "DEPOSIT", 1, "1000")
            load(page, url)
            assert page.locator(".benchmark-summary dd").all_text_contents() == [
                "0.0000%",
                "30.0000%",
                "-30.0000 percentage points",
            ]
            submit(
                page,
                record_url,
                "BUY",
                2,
                quantity="10",
                price="10",
                fees="0",
                security_id="sec_fixture_primary",
            )
            page.goto(record_url)
            fill(page, "DEPOSIT", 1, "50")
            page.locator("#id_event_date").fill("2020-01-06")
            page.get_by_role("button", name="Record transaction", exact=True).click()
            page.get_by_role("heading", name="Transactions", exact=True).wait_for()
            load(page, url)
            assert page.locator(".benchmark-summary dd").all_text_contents() == [
                "4.8600%",
                "30.0000%",
                "-25.1400 percentage points",
            ]
            table = page.get_by_role("region", name="Benchmark comparison table", exact=True)
            assert table.locator("tbody tr").count() == 4
            assert "2020-01-04" not in table.inner_text()
            assert "9.0909%" in table.inner_text()
            figure = page.locator(".chart-figure").first
            assert figure.locator("path").count() == 2
            assert figure.locator(".benchmark-line").count() == 1
            for label, width, height in (("desktop", 1280, 900), ("mobile", 390, 844)):
                page.set_viewport_size({"width": width, "height": height})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                points = figure.locator(".chart-point")
                points.first.focus()
                page.keyboard.press("End")
                assert "Portfolio 4.8600% · Benchmark 30.0000%" in figure.inner_text()
                assert points.last.get_attribute("tabindex") == "0"
                page.keyboard.press("Home")
                page.keyboard.press("ArrowRight")
                assert "2020-01-03" in figure.locator(".chart-readout").inner_text()
                figure.locator("svg").dispatch_event(
                    "pointerdown",
                    {
                        "clientX": figure.locator("svg").bounding_box()["x"] + 100,
                        "clientY": figure.locator("svg").bounding_box()["y"] + 100,
                        "pointerType": "touch",
                        "bubbles": True,
                    },
                )
                assert "Portfolio" in figure.locator(".chart-readout").inner_text()
                table.focus()
                assert table.evaluate("el => el === document.activeElement")
                page.screenshot(path=f"/tmp/stock-benchmark-{label}.png", full_page=True)
            load(page, url, end="2020-01-09")
            assert page.locator(".benchmark-summary dd").all_text_contents() == [
                "Unavailable",
                "Unavailable",
                "Unavailable",
            ]
            assert page.get_by_role("region", name="Benchmark comparison table").count() == 0
            assert (
                page.get_by_role("group", name="Portfolio and benchmark cumulative returns").count()
                == 0
            )
            response = bob.goto(url)
            assert response.status == 404
            assert "Benchmark example" not in bob.locator("main").inner_text()
            assert "no-store" in response.headers["cache-control"]
            response = owner.request.post(url, form={"benchmark_id": "sec_fixture_benchmark"})
            assert response.status == 403
            page.get_by_role("button", name="Sign out", exact=True).click()
            page.goto(url)
            assert "/sign-in/?next=" in page.url
            assert not errors
            assert all(urlsplit(request).hostname == "127.0.0.1" for request in requests)
            print(
                "Benchmark browser: matched sessions, cash/funding, exact returns/gap, "
                "missing prices, private owners/CSRF/sign-out, desktop/mobile chart "
                "keyboard/touch and table PASS (synthetic only)"
            )
        finally:
            owner.close()
            other.close()
            browser.close()


if __name__ == "__main__":
    main()
