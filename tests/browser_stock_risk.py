"""Optional actual keyboard/pointer, table and failure checks with synthetic data."""

from urllib.parse import urlsplit

from tests.browser_fundamentals import fixture_application


def main():
    from playwright.sync_api import sync_playwright

    modes = ("complete", "split", "short", "gap", "unconfirmed", "zero", "partial", "unsupported")
    with sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path="/usr/bin/chromium", headless=True)
        try:
            for mode in modes:
                with fixture_application(
                    script_name="stock_risk_fixture_server.py", script_args=(mode,)
                ) as base:
                    page = browser.new_page()
                    errors, requests = [], []
                    page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
                    page.on("request", lambda r, requests=requests: requests.append(r.url))
                    try:
                        url = base + "/stocks/sec_fixture_primary/prices/"
                        assert page.goto(url).status == 200
                        assert page.locator(".stock-risk-panel").count() == 0
                        for name, width, height in (("desktop", 1280, 900), ("mobile", 390, 844)):
                            page.set_viewport_size({"width": width, "height": height})
                            end = "2020-01-03" if mode == "short" else "2020-01-31"
                            response = page.goto(
                                url + f"?start_date=2020-01-02&end_date={end}&basis=adjusted",
                                wait_until="networkidle",
                            )
                            assert response.status == 200
                            panel = page.locator(".stock-risk-panel")
                            assert panel.is_visible()
                            assert page.evaluate(
                                "document.documentElement.scrollWidth <= window.innerWidth"
                            )
                            complete = mode in ("complete", "split", "short")
                            if complete:
                                figure = page.locator(".stock-drawdown-figure")
                                points = figure.locator(".chart-point")
                                assert points.count() == (2 if mode == "short" else 21)
                                points.first.focus()
                                page.keyboard.press("End")
                                assert "2020-01" in figure.locator(".chart-readout").inner_text()
                                assert points.last.evaluate("el => el === document.activeElement")
                                page.keyboard.press("ArrowLeft")
                                assert points.nth(points.count() - 2).evaluate(
                                    "el => el === document.activeElement"
                                )
                                page.keyboard.press("Home")
                                assert (
                                    "2020-01-02: 0.0000%"
                                    in figure.locator(".chart-readout").inner_text()
                                )
                                box = points.nth(1).bounding_box()
                                figure.locator("svg").dispatch_event(
                                    "pointerdown",
                                    {
                                        "clientX": box["x"] + box["width"] / 2,
                                        "clientY": box["y"] + box["height"] / 2,
                                    },
                                )
                                assert (
                                    "2020-01-03:" in figure.locator(".chart-readout").inner_text()
                                )
                                table = panel.locator(".stock-risk-table")
                                assert table.is_visible()
                                assert table.locator("tbody tr").count() == points.count()
                                panel.locator(".table-scroll").focus()
                                assert panel.locator(".table-scroll").evaluate(
                                    "el => el === document.activeElement"
                                )
                                assert (
                                    page.locator(".chart-figure")
                                    .first.locator(".chart-point.selected")
                                    .count()
                                    == 0
                                )
                                if mode == "split":
                                    assert (
                                        panel.locator(".stock-risk-summary dd").nth(4).inner_text()
                                        == "0.0000%"
                                    )
                                    page.get_by_label("Price basis", exact=True).select_option(
                                        "raw"
                                    )
                                    page.get_by_role(
                                        "button", name="Load prices", exact=True
                                    ).click()
                                    assert (
                                        panel.locator(".stock-risk-summary dd").nth(4).inner_text()
                                        == "50.0000%"
                                    )
                                elif mode == "complete":
                                    assert (
                                        panel.locator(".stock-risk-summary dd").nth(4).inner_text()
                                        == "25.0000%"
                                    )
                                    assert (
                                        panel.locator(".stock-risk-summary dd").nth(3).inner_text()
                                        != "Unavailable"
                                    )
                                else:
                                    assert "two session returns" in panel.inner_text()
                            else:
                                assert page.locator(".stock-drawdown-figure").count() == 0
                                assert page.locator(".stock-risk-table").count() == 0
                                assert panel.locator("[role=status]").is_visible()
                            page.screenshot(
                                path=f"/tmp/stock-risk-{mode}-{name}.png", full_page=True
                            )
                        response = page.goto(
                            url + "?start_date=2020-03-01&end_date=2020-03-31&basis=raw"
                        )
                        assert response.status == 429
                        assert page.get_by_role("alert").is_visible()
                        assert page.locator(".stock-risk-panel, .price-chart").count() == 0
                        assert not errors, errors
                        assert all(urlsplit(url).hostname == "127.0.0.1" for url in requests)
                        print(
                            f"Synthetic stock risk {mode}: desktop/mobile and failure cleanup PASS"
                        )
                    finally:
                        page.close()
        finally:
            browser.close()


if __name__ == "__main__":
    main()
