"""Optional actual desktop/mobile statement trends and chart interaction checks."""

import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.browser_fundamentals import fixture_application  # noqa: E402


def main():
    from playwright.sync_api import sync_playwright

    cases = (
        ("normal", "income_statement", "Net income", 9),
        ("normal", "balance_sheet_statement", "point-in-time observations", 9),
        ("normal", "cash_flow_statement", "netcashfromoperatingactivities", 9),
        ("mixed", "income_statement", "Classifications differ", 9),
        ("week", "income_statement", "Period lengths differ", 9),
        ("gap", "income_statement", "gap or overlap", 9),
        ("stub", "income_statement", "stub/missing dates", 6),
        ("partial", "income_statement", "Partial statement response", 6),
        ("missing", "income_statement", "Source tag netincome", 8),
    )
    with sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path="/usr/bin/chromium", headless=True)
        try:
            for mode, code, explanation, points in cases:
                with fixture_application(
                    script_name="trend_fixture_server.py", script_args=(mode,)
                ) as base:
                    page = browser.new_page(viewport={"width": 1280, "height": 900})
                    requests, errors = [], []
                    page.on(
                        "request", lambda request, requests=requests: requests.append(request.url)
                    )
                    page.on("pageerror", lambda error, errors=errors: errors.append(str(error)))
                    try:
                        page.goto(base + "/stocks/sec_fixture_primary/financials/")
                        page.get_by_role(
                            "link", name="View annual financial statement trends", exact=True
                        ).click()
                        assert page.locator(".trends-panel").count() == 0
                        page.get_by_label("Statement", exact=True).select_option(code)
                        page.get_by_label("Last fiscal year", exact=True).fill("2019")
                        page.get_by_label("Annual periods", exact=True).select_option("3")
                        page.get_by_role("button", name="Load annual trends", exact=True).click()
                        panel = page.locator(".trends-panel")
                        panel.wait_for()
                        assert explanation in panel.inner_text()
                        assert panel.locator(".trends-sources .metric-card").count() == 3
                        assert panel.locator(".chart-point").count() == points
                        assert panel.locator("table").count() == 6
                        assert "2017 FY" in panel.inner_text() and "2019 FY" in panel.inner_text()
                        assert "only when prior is positive" in panel.inner_text()
                        assert "not a point-in-time backtest dataset" in panel.inner_text()
                        figure = panel.locator(".chart-figure").first
                        selectable = figure.locator(".chart-point")
                        selectable.first.focus()
                        assert "2017 FY" in figure.locator(".chart-readout").inner_text()
                        page.keyboard.press("End")
                        assert "2019 FY" in figure.locator(".chart-readout").inner_text()
                        page.keyboard.press("Home")
                        assert "2017 FY" in figure.locator(".chart-readout").inner_text()
                        if mode == "normal":
                            page.keyboard.press("ArrowRight")
                            assert "2018 FY" in figure.locator(".chart-readout").inner_text()
                        selectable.last.hover()
                        assert "2019 FY" in figure.locator(".chart-readout").inner_text()
                        for name, width, height in (("desktop", 1280, 900), ("mobile", 390, 844)):
                            page.set_viewport_size({"width": width, "height": height})
                            assert page.evaluate(
                                "document.documentElement.scrollWidth <= window.innerWidth"
                            )
                            for table in panel.locator(".table-scroll").all():
                                table.focus()
                                assert table.evaluate(
                                    "element => element === document.activeElement"
                                )
                            page.screenshot(
                                path=f"/tmp/stock-trends-{code}-{mode}-{name}.png", full_page=True
                            )
                        response = page.goto(
                            base
                            + "/stocks/sec_fixture_primary/trends/?statement="
                            + code
                            + "&end_year=2017&years=3"
                        )
                        assert response.status == 429
                        assert response.headers["retry-after"] == "37"
                        assert response.headers["cache-control"] == "no-store"
                        assert page.locator(".trends-panel").count() == 0
                        assert page.get_by_role("alert").is_visible()
                        assert not errors, errors
                        assert all(urlsplit(url).hostname == "127.0.0.1" for url in requests)
                        print(
                            f"Test-only {code}/{mode}: desktop/mobile charts, "
                            "keyboard/pointer, tables, sources and error cleanup PASS"
                        )
                    finally:
                        page.close()
        finally:
            browser.close()


if __name__ == "__main__":
    main()
