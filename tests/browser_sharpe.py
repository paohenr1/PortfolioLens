"""Explicit Sharpe assumptions and availability through real synthetic browser loads."""

from urllib.parse import urlsplit

from browser_authentication import register
from browser_ledger import submit
from browser_portfolios import create, portfolio_application


def settings(page, url, rate="0", end="2020-01-31", confirmed=True):
    page.goto(url)
    page.locator("#id_start_date").fill("2020-01-02")
    page.locator("#id_end_date").fill(end)
    page.locator("#id_timing_checked").check()
    page.locator("#id_annual_risk_free_percent").fill(rate)
    if confirmed:
        page.locator("#id_sharpe_assumption_checked").check()
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
            register(page, base, "sharpe-browser-alice")
            register(bob, base, "sharpe-browser-bob")
            portfolio = create(page, base, "Sharpe example")
            url = portfolio + "daily-returns/"
            page.goto(url)
            assert page.locator("#id_annual_risk_free_percent").input_value() == ""
            assert page.locator(".sharpe-summary").count() == 0
            settings(page, url, confirmed=False)
            assert "Confirm the risk-free assumption" in page.locator("main").inner_text()
            assert page.locator(".sharpe-summary").count() == 0
            submit(page, portfolio + "transactions/record/", "DEPOSIT", 1, "1000")
            settings(page, url)
            assert page.locator(".sharpe-summary dd").all_text_contents()[-2:] == [
                "Unavailable",
                "Unavailable",
            ]
            assert "volatility is zero" in page.locator("main").inner_text()
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
            settings(page, url, end="2020-01-30")
            assert page.locator(".sharpe-summary dd").all_text_contents()[0] == "19"
            assert "twenty complete session returns" in page.locator("main").inner_text()
            settings(page, url)
            assert page.locator(".sharpe-summary dd").all_text_contents() == [
                "20",
                "0%",
                "0.0000%",
                "0.4545%",
                "0.0464",
                "0.7368",
            ]
            settings(page, url, rate="4")
            values = page.locator(".sharpe-summary dd").all_text_contents()
            assert values[:4] == ["20", "4%", "0.0159%", "0.4387%"]
            assert float(values[4]) < 0.0464
            assert float(values[5]) < 0.7368
            panel = page.get_by_role(
                "heading", name="Sharpe · explicit risk-free assumption"
            ).locator("..")
            for label, width, height in (("desktop", 1280, 900), ("mobile", 390, 844)):
                page.set_viewport_size({"width": width, "height": height})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                panel.screenshot(path=f"/tmp/stock-sharpe-{label}.png")
            settings(page, url, end="2020-02-03")
            values = page.locator(".sharpe-summary dd").all_text_contents()
            assert values[0] == "0" and values[-2:] == ["Unavailable", "Unavailable"]
            assert "complete valid daily session series" in page.locator("main").inner_text()
            response = bob.goto(url)
            assert response.status == 404
            assert "Sharpe example" not in bob.locator("main").inner_text()
            assert "no-store" in response.headers["cache-control"]
            assert owner.request.post(url, form={"annual_risk_free_percent": "0"}).status == 403
            page.get_by_role("button", name="Sign out", exact=True).click()
            page.goto(url)
            assert "/sign-in/?next=" in page.url
            assert not errors
            assert all(urlsplit(request).hostname == "127.0.0.1" for request in requests)
            print(
                "Sharpe browser: explicit/confirmed zero and nonzero assumptions, "
                "19/20 sample, zero volatility, exact ratios, missing data, responsive "
                "desktop/mobile and private owners/CSRF/sign-out PASS (synthetic only)"
            )
        finally:
            owner.close()
            other.close()
            browser.close()


if __name__ == "__main__":
    main()
