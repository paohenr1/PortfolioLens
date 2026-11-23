"""Navigate one selected period across private analysis screens without retyping it."""

from urllib.parse import urlsplit

from browser_authentication import register
from browser_ledger import submit
from browser_portfolios import create, portfolio_application
from playwright.sync_api import sync_playwright


def dates(page, start="2020-01-02", end="2020-01-08"):
    assert page.get_by_label("Opening valuation date:", exact=True).input_value() == start
    assert page.get_by_label("Closing valuation date:", exact=True).input_value() == end


def open_section(page, name):
    sections = page.get_by_role("navigation", name="Portfolio sections")
    sections.get_by_role("link", name=name, exact=True).click()
    assert sections.locator('[aria-current="page"]').inner_text() == name


def main():
    with portfolio_application() as base, sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path="/usr/bin/chromium", headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()
        errors, requests = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: requests.append(request.url))
        try:
            register(page, base, "analysis-context-browser")
            portfolio = create(page, base, "Remember my dates")
            submit(page, portfolio + "transactions/record/", "DEPOSIT", 1, "1000")
            page.goto(portfolio)
            automatic = page.get_by_role("region", name="Portfolio valuation")
            automatic.get_by_text("1,000.00", exact=True).wait_for()
            assert automatic.get_by_text("Closing date", exact=False).is_visible()
            page.get_by_label("Opening valuation date:", exact=True).fill("2020-01-02")
            page.get_by_label("Closing valuation date:", exact=True).fill("2020-01-08")
            page.get_by_role("checkbox").check()
            page.get_by_role("button", name="Update valuation & performance").click()
            open_section(page, "Returns")
            dates(page)
            assert not page.get_by_role("checkbox").is_checked()
            open_section(page, "Daily returns & risk")
            dates(page)
            open_section(page, "Overview")
            dates(page)
            automatic.get_by_text("1,000.00", exact=True).wait_for()
            retry_attempts = []

            def rate_limit_once(route):
                retry_attempts.append(True)
                if len(retry_attempts) == 1:
                    route.fulfill(
                        status=429,
                        headers={"Retry-After": "1", "Content-Type": "text/html"},
                        body="<div data-valuation-result>Temporarily rate-limited</div>",
                    )
                else:
                    route.continue_()

            page.route("**/overview/valuation/", rate_limit_once)
            page.get_by_role("button", name="Confirm and turn on automatic performance").click()
            automatic.get_by_text("Automatic figures will retry once", exact=False).wait_for()
            automatic.get_by_text("0.0000%", exact=True).wait_for()
            assert len(retry_attempts) == 2
            page.unroute("**/overview/valuation/", rate_limit_once)
            assert automatic.get_by_text("Jan 2, 2020 – Jan 8, 2020", exact=False).is_visible()
            page.get_by_role("button", name="Turn off automatic performance").click()
            page.get_by_role("button", name="Confirm and turn on automatic performance").wait_for()
            open_section(page, "Valuation")
            valuation_date = page.get_by_label("Valuation date:", exact=True)
            assert valuation_date.input_value() == "2020-01-08"
            valuation_date.fill("2020-01-10")
            page.get_by_role("checkbox").check()
            page.get_by_role("button", name="Load valuation", exact=True).click()
            open_section(page, "Returns")
            dates(page, end="2020-01-10")
            page.get_by_label("Closing valuation date:", exact=True).fill("2020-05-01")
            page.get_by_role("checkbox").check()
            page.get_by_role("button", name="Load returns", exact=True).click()
            open_section(page, "Daily returns & risk")
            dates(page, end="2020-05-01")
            assert "Your selected dates need adjusting here" in page.locator("main").inner_text()
            for width in (1280, 390):
                page.set_viewport_size({"width": width, "height": 900})
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert not errors, errors
            assert all(urlsplit(url).hostname == "127.0.0.1" for url in requests)
            print(
                "Analysis context PASS: dates follow overview, valuation, returns and risk, "
                "unchecked confirmations, unchanged long range and responsive layout. "
                "Cash-only fixture, no provider calls."
            )
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
