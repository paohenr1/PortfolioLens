"""Optional real-browser statement checks using explicitly synthetic observations."""

import select
import subprocess
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit


@contextmanager
def fixture_application(*, script_name="fixture_server.py", script_args=()):
    root = Path(__file__).resolve().parent.parent
    with Path("/tmp/stock-fundamentals-fixture-server.log").open("a") as diagnostics:
        process = subprocess.Popen(
            [str(root / ".venv/bin/python"), str(root / "tests" / script_name), *script_args],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=diagnostics,
            text=True,
        )
        try:
            if not select.select([process.stdout], [], [], 15)[0]:
                raise RuntimeError("The test-only statement server did not start.")
            port = int(process.stdout.readline().strip())
            yield f"http://127.0.0.1:{port}"
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def main():
    from playwright.sync_api import sync_playwright

    cases = [
        (
            "income_statement",
            "Income statement",
            [(2017, 404, "No financial statement"), (2016, 503, "did not grant access")],
        ),
        ("balance_sheet_statement", "Balance sheet", [(2018, 200, "No financial values supplied")]),
        (
            "cash_flow_statement",
            "Cash flow statement",
            [(2015, 429, "request limit has been reached")],
        ),
    ]
    with sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path="/usr/bin/chromium", headless=True)
        try:
            # Fresh test-only processes keep each scenario inside the actual quota;
            # no quota bypass or alternate production setting is introduced.
            for code, label, failures in cases:
                with fixture_application() as base:
                    page = browser.new_page(viewport={"width": 1280, "height": 900})
                    try:
                        errors, requests = [], []
                        page.on("pageerror", lambda error, errors=errors: errors.append(str(error)))
                        page.on(
                            "request",
                            lambda request, requests=requests: requests.append(request.url),
                        )
                        page.goto(base + "/search/", wait_until="networkidle")
                        page.get_by_label("Ticker or company name").fill("Fixture")
                        page.get_by_role("button", name="Search", exact=True).click()
                        page.get_by_role("link", name="Fixture Research Corp", exact=True).click()
                        page.get_by_role("link", name="View company financials", exact=True).click()
                        assert (
                            "No financial data has been requested yet"
                            in page.locator("main").inner_text()
                        )
                        page.get_by_label("Statement", exact=True).select_option(code)
                        page.get_by_label("Fiscal year", exact=True).fill("2019")
                        page.get_by_role("button", name="Load statement", exact=True).click()
                        page.get_by_role(
                            "heading", name=label + " · 2019 FY", exact=True
                        ).wait_for()
                        assert page.get_by_role("table").is_visible()
                        if code == "income_statement":
                            assert page.locator(".profitability-panel .metric-card").count() == 3
                            assert page.locator(
                                ".profitability-panel .metric-value"
                            ).all_text_contents() == ["Unavailable", "Unavailable", "-0.02%"]
                            assert "-250,000.5" in page.get_by_role("table").inner_text()
                            assert "USD per share" in page.get_by_role("table").inner_text()
                            assert (
                                "Unavailable — no unit inferred"
                                in page.get_by_role("table").inner_text()
                            )
                        elif code == "balance_sheet_statement":
                            assert page.locator(".profitability-panel").count() == 0
                            assert page.get_by_text("Balance-sheet date", exact=True).is_visible()
                        else:
                            assert page.locator(".profitability-panel").count() == 0
                            assert page.get_by_role(
                                "heading", name="Operating cash flow", exact=True
                            ).is_visible()
                        for name, width, height in [("desktop", 1280, 900), ("mobile", 390, 844)]:
                            page.set_viewport_size({"width": width, "height": height})
                            assert page.evaluate(
                                "document.documentElement.scrollWidth <= window.innerWidth"
                            )
                            page.locator(".table-scroll").focus()
                            assert page.locator(".table-scroll").evaluate(
                                "el => el === document.activeElement"
                            )
                            page.screenshot(
                                path=f"/tmp/stock-financials-{code}-{name}.png", full_page=True
                            )
                        for year, status, expected in failures:
                            response = page.goto(
                                base + "/stocks/sec_fixture_primary/financials/"
                                f"?statement_code={code}&fiscal_year={year}&fiscal_period=FY"
                            )
                            assert response.status == status
                            assert expected in page.locator("main").inner_text()
                            assert page.locator(".financial-table").count() == 0
                            assert page.locator(".profitability-panel").count() == 0
                            if status != 200:
                                assert page.get_by_role("alert").is_visible()
                        assert not errors
                        assert all(urlsplit(url).hostname == "127.0.0.1" for url in requests)
                        print(
                            f"Test-only {label}: search/select, metrics/table, "
                            "desktop/mobile, failure states PASS"
                        )
                    finally:
                        page.close()
        finally:
            browser.close()


if __name__ == "__main__":
    main()
