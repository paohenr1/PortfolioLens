"""Exercise the actual market homepage with explicitly synthetic local transport."""

from urllib.parse import urlsplit

from browser_markets_preview import ROOT, preview_application
from playwright.sync_api import sync_playwright


def main():
    output = ROOT / ".local/design-preview"
    output.mkdir(parents=True, exist_ok=True)
    with preview_application(index_fixtures=True) as base, sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path="/usr/bin/chromium", headless=True)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            errors, requests = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("request", lambda request: requests.append(request.url))
            response = page.goto(base, wait_until="networkidle")
            assert response.status == 200
            assert page.locator(".index-card").get_by_text("Not loaded", exact=True).count() == 3
            assert not page.locator(".index-value").count()
            assert not page.locator('[src$="markets-preview.js"]').count()
            page.get_by_role("button", name="Load market overview", exact=True).click()
            assert page.locator(".index-card .index-value").count() == 3
            assert page.locator(".index-card").get_by_text("103.00", exact=True).count() == 3
            assert page.locator(".sparkline path").count() == 6  # Explicit null breaks each line.
            assert page.locator(".watchbar .watch-value").count() == 5
            assert page.locator('[data-watch="10y"] .watch-value').inner_text() == "4.18%"
            assert page.locator('[data-watch="2y"] .watch-value').inner_text() == "4.03%"
            assert page.locator('[data-watch="btc"] .watch-value').inner_text() == "$110.00"
            assert page.locator('[data-watch="eur"] .watch-value').inner_text() == "1.2500"
            before_open = len(requests)
            opener = page.locator('[data-index="sp500"] .index-detail-open')
            opener.click()
            detail = page.get_by_role("dialog", name="S&P 500", exact=True)
            assert detail.is_visible()
            assert detail.locator(".chart-point").count() == 4
            assert detail.locator(".index-detail-line").count() == 2
            point = detail.locator('.chart-point[tabindex="0"]')
            point.focus()
            assert "100.00" in detail.locator(".chart-readout").inner_text()
            page.keyboard.press("End")
            assert "103.00" in detail.locator(".chart-readout").inner_text()
            assert detail.get_by_text("Range low", exact=True).is_visible()
            page.set_viewport_size({"width": 390, "height": 900})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            detail.locator(".index-chart-scroll").evaluate("el => el.scrollLeft = el.scrollWidth")
            page.keyboard.press("Escape")
            assert not detail.is_visible()
            assert opener.evaluate("el => document.activeElement === el")
            assert len(requests) == before_open, "Opening/inspecting a chart made a request"
            page.set_viewport_size({"width": 1440, "height": 1100})
            for theme in ("dark", "light"):
                page.get_by_role("combobox", name="Color theme").select_option(theme)
                page.screenshot(path=str(output / f"market-home-{theme}.png"), full_page=True)
            assert page.locator(".market-nav").count() == 1
            assert not page.locator(".workspace-links, .watch-source, .index-observations").count()
            assert "Retrieved" not in page.locator("main").inner_text()
            assert "Sources: Intrinio" in page.locator(".market-footer").inner_text()
            page.get_by_role("button", name="Customize", exact=True).click()
            dialog = page.get_by_role("dialog")
            dialog.get_by_label("Bitcoin / USD").uncheck()
            dialog.get_by_role("button", name="Save preferences").click()
            assert not page.locator('[data-watch="btc"]').is_visible()
            for width in (1024, 768, 390):
                page.set_viewport_size({"width": width, "height": 900})
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            # All navigation destinations share colors and the saved theme,
            # including sign-in screens for private portfolio/watchlist routes.
            for theme in ("dark", "light"):
                page.get_by_role("combobox", name="Color theme").select_option(theme)
                expected = page.locator("body").evaluate(
                    "el => getComputedStyle(el).backgroundColor"
                )
                for label in ("My Portfolio", "Research", "Watchlists", "Markets"):
                    page.get_by_role("navigation", name="Main navigation").get_by_role(
                        "link", name=label, exact=True
                    ).click()
                    assert page.locator("html").get_attribute("data-theme") == theme
                    assert page.get_by_role("combobox", name="Color theme").input_value() == theme
                    assert (
                        page.locator("body").evaluate("el => getComputedStyle(el).backgroundColor")
                        == expected
                    )
            assert not errors, errors
            assert all(urlsplit(request).hostname == "127.0.0.1" for request in requests)
            print(
                "Market homepage PASS: explicit CSRF load, three indices, five sourced indicators, "
                "null gaps, detailed index inspection, concise sources, "
                "honest unavailable widgets, "
                "themes, watchbar controls, and responsive layout. Synthetic local transport only."
            )
        finally:
            browser.close()


if __name__ == "__main__":
    main()
