"""Real chart controls and error cleanup with explicitly synthetic volume data."""

from urllib.parse import urlsplit

from tests.browser_fundamentals import fixture_application


def inspect_chart(page, panel, expected_count):
    figure = panel.locator(".volume-figure")
    points = figure.locator(".chart-point")
    assert points.count() == expected_count
    assert panel.locator(".volume-bar").count() == expected_count
    points.first.focus()
    page.keyboard.press("End")
    assert points.last.evaluate("el => el === document.activeElement")
    assert "2020-01" in figure.locator(".chart-readout").inner_text()
    page.keyboard.press("Home")
    assert points.first.evaluate("el => el === document.activeElement")
    if expected_count > 1:
        page.keyboard.press("ArrowRight")
        assert points.nth(1).evaluate("el => el === document.activeElement")
    box = points.first.bounding_box()
    figure.locator("svg").dispatch_event(
        "pointerdown",
        {
            "clientX": box["x"] + box["width"] / 2,
            "clientY": box["y"] + box["height"] / 2,
        },
    )
    assert "2020-01" in figure.locator(".chart-readout").inner_text()


def main():
    from playwright.sync_api import sync_playwright

    modes = (
        "complete",
        "zero",
        "missing",
        "unconfirmed",
        "volume-only",
        "partial",
        "empty",
        "invalid",
    )
    with sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path="/usr/bin/chromium", headless=True)
        try:
            for mode in modes:
                with fixture_application(
                    script_name="volume_fixture_server.py", script_args=(mode,)
                ) as base:
                    page = browser.new_page()
                    errors, destinations = [], []
                    page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
                    page.on(
                        "request",
                        lambda r, destinations=destinations: destinations.append(
                            urlsplit(r.url).hostname
                        ),
                    )
                    try:
                        url = base + "/stocks/sec_fixture_primary/prices/"
                        assert page.goto(url).status == 200
                        assert page.locator(".volume-panel").count() == 0
                        for name, width, height in (("desktop", 1280, 900), ("mobile", 390, 844)):
                            page.set_viewport_size({"width": width, "height": height})
                            end = "2020-01-08" if mode == "partial" else "2020-01-06"
                            response = page.goto(
                                url
                                + f"?start_date=2020-01-02&end_date={end}"
                                + "&basis=adjusted&volume_basis=raw",
                                wait_until="networkidle",
                            )
                            assert response.status == (503 if mode == "invalid" else 200)
                            if mode == "invalid":
                                assert page.get_by_role("alert").is_visible()
                                assert (
                                    page.locator(
                                        ".price-chart, .volume-panel, .stock-risk-panel"
                                    ).count()
                                    == 0
                                )
                                continue
                            panel = page.locator(".volume-panel")
                            assert panel.is_visible()
                            count = {
                                "complete": 3,
                                "zero": 3,
                                "unconfirmed": 1,
                                "volume-only": 3,
                                "partial": 4,
                            }.get(mode, 0)
                            if count:
                                inspect_chart(page, panel, count)
                                assert page.locator("script[src$='prices.js']").count() == 1
                                if mode == "zero":
                                    assert panel.locator(".chart-point").evaluate_all(
                                        "els => els.every(e => e.getAttribute('cy') === '285')"
                                    )
                                    assert (
                                        "0 shares"
                                        in panel.locator(".volume-summary dd").first.inner_text()
                                    )
                                elif mode == "complete":
                                    assert (
                                        "1000.125 shares"
                                        in panel.locator(".chart-readout").inner_text()
                                    )
                                    assert (
                                        page.locator(
                                            ".stock-drawdown-figure .chart-point.selected"
                                        ).count()
                                        == 0
                                    )
                            else:
                                assert panel.locator(".volume-figure").count() == 0
                                assert "No completed volume available" in panel.inner_text()
                            if mode != "empty":
                                panel.locator("summary").focus()
                                page.keyboard.press("Enter")
                                assert panel.locator(".volume-table").is_visible()
                                panel.locator(".table-scroll").focus()
                                assert panel.locator(".table-scroll").evaluate(
                                    "el => el === document.activeElement"
                                )
                            if mode == "complete":
                                page.get_by_label("Volume basis", exact=True).select_option(
                                    "adjusted"
                                )
                                page.get_by_role("button", name="Load prices", exact=True).click()
                                inspect_chart(page, panel, 2)
                                assert "Adjusted volume · Daily share volume" in panel.inner_text()
                                assert (
                                    "2020-01-02: 500.0625 provider-adjusted shares"
                                    in panel.locator(".chart-readout").inner_text()
                                )
                                assert page.get_by_role(
                                    "heading", name="Adjusted close · USD", exact=True
                                ).is_visible()
                            assert page.evaluate(
                                "document.documentElement.scrollWidth <= window.innerWidth"
                            )
                            page.screenshot(
                                path=f"/tmp/stock-volume-{mode}-{name}.png", full_page=True
                            )
                        response = page.goto(
                            url
                            + "?start_date=2020-03-01&end_date=2020-03-31"
                            + "&basis=raw&volume_basis=raw"
                        )
                        assert response.status == 429
                        assert page.get_by_role("alert").is_visible()
                        assert (
                            page.locator(".price-chart, .stock-risk-panel, .volume-panel").count()
                            == 0
                        )
                        assert not errors, errors
                        assert all(host == "127.0.0.1" for host in destinations)
                        print(
                            f"Synthetic volume {mode}: desktop/mobile, "
                            "controls/table and cleanup PASS"
                        )
                    finally:
                        page.close()
        finally:
            browser.close()


if __name__ == "__main__":
    main()
