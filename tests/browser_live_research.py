"""Opt-in real Intrinio acceptance: at most 32 backend calls, no saved data."""

import argparse
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import urlsplit

from browser_acceptance import RequestPacer, responsive
from browser_portfolios import portfolio_application

START, END, YEAR = "2026-08-12", "2026-10-09", "2025"


def submit(page, pacer, button, cost):
    pacer.before(cost)
    with page.expect_navigation(wait_until="domcontentloaded") as navigation:
        page.get_by_role("button", name=button, exact=True).click()
    response = navigation.value
    assert response.status == 200, "The live research load did not succeed."
    assert "no-store" in response.headers["cache-control"]
    assert page.get_by_role("alert").count() == 0


def number(text):
    assert text != "Unavailable", "A required live observation is unavailable."
    value = Decimal(text.replace(",", ""))
    assert value.is_finite(), "A live observation is not finite."
    return value


def rounded(value):
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def check_chart(page, figure):
    points = figure.locator(".chart-point")
    assert points.count() >= 2
    points.first.focus()
    page.keyboard.press("End")
    assert points.last.evaluate("el => el === document.activeElement")
    assert figure.locator(".chart-readout").inner_text() == points.last.get_attribute("data-label")
    page.keyboard.press("Home")
    assert points.first.evaluate("el => el === document.activeElement")


def search(page, base, pacer, ticker):
    assert page.goto(base + "/search/").status == 200
    page.get_by_label("Ticker or company name", exact=True).fill(ticker)
    submit(page, pacer, "Search", 1)
    card = page.locator(".result-card").filter(has_text=ticker)
    card = card.filter(has_text="XNAS").filter(has_text="USD")
    assert card.count() == 1, "The requested USD/XNAS listing is ambiguous or unavailable."
    return base + card.get_by_role("link").get_attribute("href")


def prices(page, root, pacer, price_basis, volume_basis):
    assert page.goto(root + "prices/").status == 200
    page.get_by_label("Start date", exact=True).fill(START)
    page.get_by_label("End date", exact=True).fill(END)
    page.get_by_label("Price basis", exact=True).select_option(price_basis)
    page.get_by_label("Volume basis", exact=True).select_option(volume_basis)
    submit(page, pacer, "Load prices", 1)
    assert page.locator(".stock-risk-panel").is_visible()
    assert page.locator(".stock-risk-summary dd").count() >= 5
    assert all(
        value != "Unavailable"
        for value in page.locator(".stock-risk-summary dd").all_text_contents()
    ), "A required live stock risk result is unavailable."
    check_chart(page, page.locator(".stock-drawdown-figure"))
    check_chart(page, page.locator(".volume-figure"))
    assert page.locator(".stock-risk-table tbody tr").count() == 42
    page.locator(".volume-panel summary").click()
    assert page.locator(".volume-table").is_visible()
    assert page.locator(".volume-table tbody tr").count() == 42
    responsive(page)


def main():
    from playwright.sync_api import sync_playwright

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--financial-follow-up",
        action="store_true",
        help="26-call follow-up; skip previously verified prices and market capitalization.",
    )
    follow_up = parser.parse_args().financial_follow_up
    maximum = 26 if follow_up else 32
    counts, errors, hosts = [], [], []
    with (
        portfolio_application(
            live_market_data=True, max_live_requests=maximum, live_request_counts=counts
        ) as base,
        sync_playwright() as driver,
    ):
        browser = driver.chromium.launch(executable_path="/usr/bin/chromium", headless=True)
        page = browser.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: hosts.append(urlsplit(request.url).hostname))
        pacer = RequestPacer()
        try:
            root = search(page, base, pacer, "AAPL")
            if not follow_up:
                pacer.before(1)
                assert page.goto(root).status == 200
                assert "XNAS" in page.locator("main").inner_text()
                assert "USD" in page.locator("main").inner_text()
                prices(page, root, pacer, "raw", "adjusted")
                print("Live AAPL identity, daily prices, volume and stock risk PASS.", flush=True)

            assert page.goto(root + "financials/").status == 200
            page.get_by_label("Statement", exact=True).select_option("income_statement")
            page.get_by_label("Fiscal year", exact=True).fill(YEAR)
            page.get_by_label("Fiscal period", exact=True).select_option("FY")
            submit(page, pacer, "Load statement", 3)
            supplied = {}
            for row in page.locator(".financial-table tbody tr").all():
                cells = row.locator("td").all_text_contents()
                if cells[2] in (
                    "totalrevenue",
                    "totalgrossprofit",
                    "totaloperatingincome",
                    "netincome",
                ):
                    assert cells[1] == "USD"
                    supplied[cells[2]] = number(cells[0])
            revenue = supplied["totalrevenue"]
            assert revenue > 0
            for card, tag in zip(
                page.locator(".profitability-metrics .metric-card").all(),
                ("totalgrossprofit", "totaloperatingincome", "netincome"),
                strict=True,
            ):
                actual = card.locator(".metric-value").inner_text()
                assert actual.endswith("%"), card.locator("p.muted").first.inner_text()
                assert number(actual[:-1]) == rounded(supplied[tag] / revenue * 100)
            responsive(page)
            print("Live AAPL FY2025 margins: independent arithmetic PASS.", flush=True)

            assert page.goto(root + "returns-on-capital/").status == 200
            page.get_by_label("Fiscal year", exact=True).fill(YEAR)
            submit(page, pacer, "Load annual returns", 7)
            assert page.locator(".capital-sources .metric-card").count() == 3
            income = number(page.locator(".capital-period dd").last.inner_text())
            cards = page.locator(".capital-return-metrics .metric-card")
            assert cards.count() == 2
            for card in cards.all():
                opening, closing, average = map(number, card.locator("dd").all_text_contents())
                assert average == (opening + closing) / 2
                actual = card.locator(".metric-value").inner_text()
                assert actual.endswith("%")
                assert number(actual[:-1]) == rounded(income / average * 100)
            responsive(page)
            print("Live AAPL FY2025 ROA/ROE: independent arithmetic PASS.", flush=True)

            assert page.goto(root + "growth/").status == 200
            page.get_by_label("Current fiscal year", exact=True).fill(YEAR)
            submit(page, pacer, "Load annual growth", 5)
            assert page.locator(".growth-sources .metric-card").count() == 2
            cards = page.locator(".growth-metrics .metric-card")
            assert cards.count() == 2
            for card in cards.all():
                prior, current, change = map(number, card.locator("dd").all_text_contents())
                assert change == current - prior
                actual = card.locator(".metric-value").inner_text()
                assert actual.endswith("%")
                assert number(actual[:-1]) == rounded(change / prior * 100)
            responsive(page)
            print("Live AAPL FY2024/2025 growth: independent arithmetic PASS.", flush=True)

            assert page.goto(root + "multiples/").status == 200
            page.get_by_label("Earnings fiscal year", exact=True).fill(YEAR)
            page.get_by_label("Raw closing price date", exact=True).fill(END)
            # Exercise the explicit assumption; this does not verify compatibility.
            page.get_by_role("checkbox").check()
            submit(page, pacer, "Load annual P/E", 4)
            assert page.locator(".multiples-sources .metric-card").count() == 2
            panel = page.locator(".multiples-panel")
            assert "not independently verified" in panel.inner_text()
            assert "historical-as-known" in panel.inner_text()
            close = number(panel.locator(".reference-grid dd").nth(4).inner_text())
            cards = panel.locator(".multiples-metrics .metric-card")
            assert cards.count() == 2
            for card in cards.all():
                eps = number(card.locator("dd").inner_text())
                actual = card.locator(".metric-value").inner_text()
                assert actual.endswith("×")
                assert number(actual[:-1]) == rounded(close / eps)
            responsive(page)
            print("Live AAPL annual P/E: arithmetic and assumption labels PASS.", flush=True)

            assert page.goto(root + "trends/").status == 200
            page.get_by_label("Statement", exact=True).select_option("income_statement")
            page.get_by_label("Last fiscal year", exact=True).fill(YEAR)
            page.get_by_label("Annual periods", exact=True).select_option("2")
            submit(page, pacer, "Load annual trends", 5)
            assert page.locator(".trends-sources .metric-card").count() == 2
            panels = page.locator(".trend-metric")
            assert panels.count() == 3
            for panel in panels.all():
                check_chart(page, panel.locator(".chart-figure"))
                observations = panel.locator("table").first.locator("tbody tr td:first-of-type")
                prior, current = map(number, observations.all_text_contents())
                change = panel.locator("table").last.locator("tbody tr td")
                assert number(change.nth(0).inner_text()) == current - prior
                actual = change.nth(1).inner_text()
                assert actual.endswith("%")
                assert number(actual[:-1]) == rounded((current - prior) / prior * 100)
            responsive(page)
            print("Live AAPL annual trends: charts, tables and arithmetic PASS.", flush=True)

            if not follow_up:
                assert page.goto(root + "market-cap/").status == 200
                page.get_by_label("Market capitalization date", exact=True).fill(END)
                submit(page, pacer, "Load market capitalization", 3)
                panel = page.locator(".capitalization-panel")
                assert number(panel.locator(".metric-value").inner_text()) > 0
                assert "marketcap / usd" in panel.inner_text()
                assert "Underlying price date / timestamp" in panel.inner_text()
                assert "Unavailable · not supplied by this endpoint" in panel.inner_text()
                responsive(page)
                print("Live AAPL company market cap: source/date limitations PASS.", flush=True)

            microsoft = search(page, base, pacer, "MSFT")
            if not follow_up:
                prices(page, microsoft, pacer, "adjusted", "raw")
            print("Live MSFT USD/XNAS listing acceptance PASS.", flush=True)
            assert not errors, "The live browser reported a JavaScript error."
            assert all(host == "127.0.0.1" for host in hosts)
        finally:
            page.close()
            browser.close()
    assert counts == [maximum], "Live acceptance used an unexpected backend request count."
    print(f"Live acceptance PASS: {maximum} bounded backend calls; no saved provider data.")


if __name__ == "__main__":
    main()
