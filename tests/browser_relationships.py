"""Synthetic relationship sample gates and coefficients on an isolated real app."""

from urllib.parse import urlsplit

from browser_authentication import register
from browser_ledger import submit
from browser_portfolios import create, portfolio_application


def load(page, url, end="2020-01-31"):
    page.goto(url)
    page.locator("#id_start_date").fill("2020-01-02")
    page.locator("#id_end_date").fill(end)
    page.locator("#id_timing_checked").check()
    page.locator("#id_benchmark_id").fill("sec_fixture_relationship")
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
            register(page, base, "relationship-browser-alice")
            register(bob, base, "relationship-browser-bob")
            portfolio = create(page, base, "Relationship example")
            url = portfolio + "daily-returns/"
            page.goto(url)
            assert page.locator(".relationship-summary").count() == 0
            submit(page, portfolio + "transactions/record/", "DEPOSIT", 1, "1000")
            load(page, url)
            assert page.locator(".relationship-summary dd").all_text_contents() == [
                "20",
                "Unavailable",
                "0.0000",
            ]
            assert "Portfolio return variance is zero" in page.locator("main").inner_text()
            submit(
                page,
                portfolio + "transactions/record/",
                "BUY",
                2,
                quantity="100",
                price="10",
                fees="0",
                security_id="sec_fixture_relationship",
            )
            load(page, url, end="2020-01-30")
            assert page.locator(".relationship-summary dd").all_text_contents() == [
                "19",
                "Unavailable",
                "Unavailable",
            ]
            assert "at least twenty matched session returns" in page.locator("main").inner_text()
            load(page, url)
            assert page.locator(".relationship-summary dd").all_text_contents() == [
                "20",
                "1.0000",
                "1.0000",
            ]
            assert page.locator(".benchmark-summary dd").all_text_contents() == [
                "0.0000%",
                "0.0000%",
                "0.0000 percentage points",
            ]
            assert (
                page.get_by_role("region", name="Benchmark comparison table")
                .locator("tbody tr")
                .count()
                == 20
            )
            panel = page.get_by_role(
                "heading", name="Correlation and beta · matched daily returns"
            ).locator("..")
            for label, width, height in (("desktop", 1280, 900), ("mobile", 390, 844)):
                page.set_viewport_size({"width": width, "height": height})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                panel.screenshot(path=f"/tmp/stock-relationship-{label}.png")
                figure = page.locator(".chart-figure").first
                figure.locator(".chart-point").first.focus()
                page.keyboard.press("End")
                assert "2020-01-31" in figure.locator(".chart-readout").inner_text()
                assert "Portfolio 0.0000% · Benchmark 0.0000%" in figure.inner_text()
            load(page, url, end="2020-02-03")
            assert page.locator(".relationship-summary dd").all_text_contents() == [
                "0",
                "Unavailable",
                "Unavailable",
            ]
            assert "complete valid matched daily series" in page.locator("main").inner_text()
            response = bob.goto(url)
            assert response.status == 404
            assert "Relationship example" not in bob.locator("main").inner_text()
            assert "no-store" in response.headers["cache-control"]
            response = owner.request.post(url, form={"benchmark_id": "sec_fixture_relationship"})
            assert response.status == 403
            page.get_by_role("button", name="Sign out", exact=True).click()
            page.goto(url)
            assert "/sign-in/?next=" in page.url
            assert not errors
            assert all(urlsplit(request).hostname == "127.0.0.1" for request in requests)
            print(
                "Relationship browser: 19/20 sample gate, cash zero slope/undefined correlation, "
                "unit correlation/beta, missing data, responsive desktop/mobile, "
                "chart keyboard, owners/CSRF/sign-out PASS (synthetic only)"
            )
        finally:
            owner.close()
            other.close()
            browser.close()


if __name__ == "__main__":
    main()
