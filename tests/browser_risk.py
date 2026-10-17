"""Observed risk/chart interactions on an isolated PostgreSQL browser database."""

from urllib.parse import urlsplit

from browser_authentication import register
from browser_daily_returns import load
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
            for context in (owner, other):
                context.on("request", lambda request: requests.append(request.url))
            for current in (page, bob):
                current.on("pageerror", lambda error: errors.append(str(error)))
            register(page, base, "risk-browser-alice")
            register(bob, base, "risk-browser-bob")
            portfolio = create(page, base, "Risk browser example")
            page.get_by_role("link", name="View daily returns and risk", exact=True).click()
            url = page.url
            assert page.locator(".risk-summary").count() == 0
            submit(page, portfolio + "transactions/record/", "DEPOSIT", 1, "1000")
            submit(
                page,
                portfolio + "transactions/record/",
                "BUY",
                2,
                quantity="100",
                price="10",
                fees="0",
                security_id="sec_fixture_risk",
            )
            load(page, url)
            assert page.locator(".risk-summary dd").all_text_contents() == [
                "4",
                "28.9756%",
                "Unavailable",
                "25.0000%",
                "2020-01-03",
                "2020-01-06",
                "2020-01-07",
            ]
            assert "twenty session returns" in page.locator("main").inner_text()
            table = page.get_by_role("region", name="Drawdown observation table", exact=True)
            assert table.locator("tbody tr").count() == 5
            assert table.locator("tbody td").all_text_contents() == [
                "0.0000%",
                "0.0000%",
                "-25.0000%",
                "0.0000%",
                "-20.0000%",
            ]
            chart = page.locator(".chart-figure")
            points = chart.locator(".chart-point")
            for label, width, height in (("desktop", 1280, 900), ("mobile", 390, 844)):
                page.set_viewport_size({"width": width, "height": height})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                points.nth(0).focus()
                page.keyboard.press("ArrowRight")
                assert (
                    chart.locator(".chart-readout").inner_text() == "2020-01-03: 0.0000% drawdown"
                )
                page.keyboard.press("ArrowRight")
                assert (
                    chart.locator(".chart-readout").inner_text() == "2020-01-06: -25.0000% drawdown"
                )
                page.keyboard.press("End")
                assert (
                    chart.locator(".chart-readout").inner_text() == "2020-01-08: -20.0000% drawdown"
                )
                page.keyboard.press("Home")
                assert (
                    chart.locator(".chart-readout").inner_text() == "2020-01-02: 0.0000% drawdown"
                )
                points.nth(0).click()
                assert (
                    chart.locator(".chart-readout").inner_text() == "2020-01-02: 0.0000% drawdown"
                )
                table.focus()
                assert table.evaluate("el => el === document.activeElement")
                page.screenshot(path=f"/tmp/stock-risk-{label}.png", full_page=True)
            load(page, url, "2020-01-09")
            assert page.locator(".risk-summary dd").all_text_contents()[1:4] == ["Unavailable"] * 3
            assert page.locator(".chart-figure").count() == 0
            load(page, url, "2020-01-03")
            assert page.locator(".risk-summary dd").all_text_contents()[:4] == [
                "1",
                "Unavailable",
                "Unavailable",
                "0.0000%",
            ]
            assert "at least two session returns" in page.locator("main").inner_text()
            response = bob.goto(url)
            assert response.status == 404
            assert "Risk browser example" not in bob.locator("main").inner_text()
            assert "no-store" in response.headers["cache-control"]
            response = owner.request.post(
                url,
                form={"start_date": "2020-01-02", "end_date": "2020-01-08", "timing_checked": "on"},
            )
            assert response.status == 403
            page.get_by_role("button", name="Sign out", exact=True).click()
            page.goto(url)
            assert "/sign-in/?next=" in page.url
            assert not errors
            assert all(urlsplit(request).hostname == "127.0.0.1" for request in requests)
            print(
                "Risk browser: volatility, peak/trough/recovery, drawdown table, short/missing "
                "samples, mouse/keyboard chart, privacy, CSRF and desktop/mobile "
                "PASS (synthetic only)"
            )
        finally:
            owner.close()
            other.close()
            browser.close()


if __name__ == "__main__":
    main()
