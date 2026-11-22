"""Exercise the actual market homepage with explicitly synthetic local transport."""

import os
import select
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


@contextmanager
def market_application():
    with (ROOT / ".local/market-homepage/server.log").open("w") as diagnostics:
        process = subprocess.Popen(
            [str(ROOT / ".venv/bin/python"), __file__, "--serve"],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=diagnostics,
            text=True,
            env={
                **os.environ,
                "DJANGO_ENV": "development",
                "DJANGO_DEBUG": "true",
                "DJANGO_PRIVATE_SITE": "false",
                "INTRINIO_API_KEY": "index-browser-fixture-key",
            },
        )
        try:
            if not select.select([process.stdout], [], [], 15)[0]:
                raise RuntimeError("Markets fixture server failed to start")
            port = int(process.stdout.readline().strip())
            yield f"http://127.0.0.1:{port}"
        finally:
            process.terminate()
            process.wait(timeout=10)


def serve():
    import django

    django.setup()
    from wsgiref.simple_server import WSGIRequestHandler, make_server

    from django.contrib.staticfiles.handlers import StaticFilesHandler
    from django.core.wsgi import get_wsgi_application

    class QuietHandler(WSGIRequestHandler):
        def log_message(self, *args):
            pass

    with make_server(
        "127.0.0.1", 0, StaticFilesHandler(get_wsgi_application()), handler_class=QuietHandler
    ) as server:
        from datetime import date, timedelta
        from unittest.mock import patch

        import httpx

        from market_data.indices import INDEX_CATALOG
        from market_data.intrinio import IntrinioClient

        def transport(request):
            symbol = request.url.path.split("/")[3]
            key = next(key for key, spec in INDEX_CATALOG.items() if spec[0] == symbol)
            end = date.fromisoformat(request.url.params["end_date"])
            values = [100, 101, None, 102, 103]
            return httpx.Response(
                200,
                json={
                    "index": {"symbol": symbol, "id": INDEX_CATALOG[key][1]},
                    "historical_data": [
                        {"date": (end - timedelta(days=4 - i)).isoformat(), "value": value}
                        for i, value in enumerate(values)
                    ],
                    "next_page": None,
                },
            )

        def factory(key):
            return IntrinioClient(key, transport=httpx.MockTransport(transport))

        from market_data.public_markets import (
            ATOM,
            DATA,
            FX_URL,
            METADATA,
            TREASURY_URL,
            PublicMarketClient,
        )

        def public_transport(request):
            end = date.today() - timedelta(days=1)
            if str(request.url).startswith(TREASURY_URL):
                entries = "".join(
                    f"<entry><content><m:properties><d:NEW_DATE>{day.isoformat()}T00:00:00"
                    f"</d:NEW_DATE><d:BC_2YEAR>{two}</d:BC_2YEAR>"
                    f"<d:BC_10YEAR>{ten}</d:BC_10YEAR></m:properties></content></entry>"
                    for day, two, ten in (
                        (end - timedelta(days=1), "4.00", "4.20"),
                        (end, "4.03", "4.18"),
                    )
                    if day.year == date.today().year
                )
                return httpx.Response(
                    200,
                    content=(
                        f'<feed xmlns="{ATOM[1:-1]}" xmlns:d="{DATA[1:-1]}" '
                        f'xmlns:m="{METADATA[1:-1]}">{entries}</feed>'
                    ).encode(),
                )
            if str(request.url).startswith(FX_URL):
                return httpx.Response(
                    200,
                    json={
                        "seriesDetail": {
                            "FXUSDCAD": {"label": "USD/CAD"},
                            "FXEURCAD": {"label": "EUR/CAD"},
                        },
                        "observations": [
                            {
                                "d": (end - timedelta(days=1)).isoformat(),
                                "FXUSDCAD": {"v": "1.20"},
                                "FXEURCAD": {"v": "1.44"},
                            },
                            {
                                "d": end.isoformat(),
                                "FXUSDCAD": {"v": "1.25"},
                                "FXEURCAD": {"v": "1.5625"},
                            },
                        ],
                    },
                )
            return httpx.Response(200, json={"open": "100", "last": "110"})

        def public_factory(**kwargs):
            return PublicMarketClient(**kwargs, transport=httpx.MockTransport(public_transport))

        with (
            patch("research.services.IntrinioClient", side_effect=factory),
            patch("research.watchbar.PublicMarketClient", side_effect=public_factory),
        ):
            print(server.server_port, flush=True)
            server.serve_forever()


def main():
    from playwright.sync_api import sync_playwright

    output = ROOT / ".local/market-homepage"
    output.mkdir(parents=True, exist_ok=True)
    with market_application() as base, sync_playwright() as driver:
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
    if "--serve" in sys.argv:
        serve()
    else:
        main()
