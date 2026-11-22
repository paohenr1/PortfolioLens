"""Optional browser checks using the environment's existing Playwright/Chromium."""

from urllib.parse import urlsplit

from browser_fundamentals import fixture_application


def main():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path="/usr/bin/chromium", headless=True)
        try:
            for name, width, height in [("desktop", 1280, 900), ("mobile", 390, 844)]:
                with fixture_application() as base_url:
                    page = browser.new_page(viewport={"width": width, "height": height})
                    errors = []
                    requests = []
                    page.on("pageerror", lambda error, errors=errors: errors.append(str(error)))
                    page.on(
                        "request", lambda request, requests=requests: requests.append(request.url)
                    )
                    response = page.goto(base_url + "/search/", wait_until="networkidle")
                    assert response.status == 200
                    assert page.evaluate("document.documentElement.dataset.theme === 'dark'")
                    page.get_by_label("Ticker or company name").fill("Fixture")
                    page.get_by_role("button", name="Search", exact=True).click()
                    page.get_by_role("heading", name="Search results", exact=True).wait_for()
                    assert page.locator(".result-card").count() == 2
                    assert page.evaluate(
                        "document.documentElement.scrollWidth <= window.innerWidth"
                    )
                    page.screenshot(path=f"/tmp/stock-search-{name}.png", full_page=True)
                    page.get_by_role("link", name="Fixture Research Corp", exact=True).click()
                    assert page.locator(".company-close").inner_text().strip() == "15.5 USD"
                    assert page.locator(".company-price .price-chart").is_visible()
                    assert page.get_by_role(
                        "heading", name="Annual financial highlights"
                    ).is_visible()
                    page.get_by_text("Listing details", exact=True).click()
                    assert (
                        page.locator("details .reference-grid")
                        .get_by_text("USD", exact=True)
                        .is_visible()
                    )
                    assert (
                        page.locator(".reference-grid")
                        .get_by_text("2020-01-02", exact=True)
                        .is_visible()
                    )
                    assert page.evaluate(
                        "document.documentElement.scrollWidth <= window.innerWidth"
                    )
                    page.get_by_role("link", name="View price history", exact=True).click()
                    page.get_by_label("Start date", exact=True).fill("2020-01-01")
                    page.get_by_label("End date", exact=True).fill("2020-01-31")
                    page.get_by_role("button", name="Load prices", exact=True).click()
                    page.get_by_role("heading", name="Adjusted close · USD", exact=True).wait_for()
                    assert page.locator(".chart-point").count() == 4
                    assert page.locator(".chart-line").count() == 2
                    assert "14.5 USD" in page.locator(".price-summary dd").first.inner_text()
                    svg = page.locator(".price-chart")
                    svg.dispatch_event("pointermove", {"clientX": 200, "clientY": 300})
                    assert "2020-01" in page.locator(".chart-readout").inner_text()
                    if name == "mobile":
                        svg.dispatch_event("pointerdown", {"clientX": 250, "clientY": 300})
                        assert page.locator(".chart-point.selected").count() == 1
                    page.locator(".price-table-details summary").focus()
                    page.keyboard.press("Enter")
                    assert page.get_by_role("table").is_visible()
                    assert (
                        page.get_by_role("table")
                        .get_by_text("Unavailable", exact=True)
                        .is_visible()
                    )
                    assert page.evaluate(
                        "document.documentElement.scrollWidth <= window.innerWidth"
                    )
                    page.screenshot(path=f"/tmp/stock-prices-{name}.png", full_page=True)
                    for query, expected, status in (
                        [
                            ("fixture-empty", "No matching instruments", 200),
                            ("fixture-rate-limit", "request limit has been reached", 429),
                            ("fixture-auth-error", "could not authenticate", 503),
                        ]
                        if name == "desktop"
                        else []
                    ):
                        response = page.goto(base_url + "/search/?q=" + query)
                        assert response.status == status
                        assert expected in page.locator("main").inner_text()
                        if status != 200:
                            assert page.get_by_role("alert").is_visible()
                    if name == "mobile":
                        response = page.goto(
                            base_url + "/stocks/sec_fixture_primary/prices/"
                            "?start_date=2020-03-01&end_date=2020-03-31&basis=adjusted"
                        )
                        assert response.status == 429
                        assert page.get_by_role("alert").is_visible()
                        assert page.locator(".price-chart").count() == 0
                    assert not errors, errors
                    assert all(urlsplit(url).hostname == "127.0.0.1" for url in requests)
                    print(f"Test-only {name}: search, select, details, prices, chart/table PASS")
                    page.close()
        finally:
            browser.close()


if __name__ == "__main__":
    main()
