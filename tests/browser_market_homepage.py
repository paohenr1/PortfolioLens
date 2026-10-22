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
            assert page.get_by_text("Not loaded", exact=True).count() == 3
            assert not page.locator(".index-value").count()
            assert not page.locator('[src$="markets-preview.js"]').count()
            page.get_by_role("button", name="Load daily levels", exact=True).click()
            assert page.locator(".index-value").count() == 3
            assert page.get_by_text("103.00", exact=True).count() == 3
            assert page.locator(".sparkline path").count() == 6  # Explicit null breaks each line.
            assert page.get_by_text("Not connected", exact=True).count() == 5
            for theme in ("dark", "light"):
                page.get_by_role("combobox", name="Color theme").select_option(theme)
                page.screenshot(path=str(output / f"market-home-{theme}.png"), full_page=True)
            page.locator(".index-observations summary").first.focus()
            page.keyboard.press("Enter")
            assert page.get_by_role("table").first.is_visible()
            assert "Unavailable" in page.get_by_role("table").first.inner_text()
            page.get_by_role("button", name="Customize", exact=True).click()
            dialog = page.get_by_role("dialog")
            dialog.get_by_label("Bitcoin / USD").uncheck()
            dialog.get_by_role("button", name="Save preferences").click()
            assert not page.locator('[data-watch="btc"]').is_visible()
            for width in (1024, 768, 390):
                page.set_viewport_size({"width": width, "height": 900})
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert not errors, errors
            assert all(urlsplit(request).hostname == "127.0.0.1" for request in requests)
            print(
                "Market homepage PASS: explicit CSRF form load, three dated index cards, "
                "null gaps, accessible observation tables, honest unavailable widgets, "
                "themes, watchbar controls, and responsive layout. Synthetic local transport only."
            )
        finally:
            browser.close()


if __name__ == "__main__":
    main()
