"""Local synthetic preview: themes, keyboard controls, persistence, CSP and layout."""

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
def preview_application(*, index_fixtures=False):
    with (ROOT / ".local/markets-preview-server.log").open("w") as diagnostics:
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
                "INTRINIO_API_KEY": "index-browser-fixture-key" if index_fixtures else "",
                "STOCK_INDEX_BROWSER_FIXTURES": "1" if index_fixtures else "0",
            },
        )
        try:
            if not select.select([process.stdout], [], [], 15)[0]:
                raise RuntimeError("Preview server failed to start; inspect .local log")
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
        from contextlib import ExitStack, nullcontext
        from unittest.mock import patch

        context = nullcontext()
        if os.environ.get("STOCK_INDEX_BROWSER_FIXTURES") == "1":
            from datetime import date, timedelta

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

            context = ExitStack()
            context.enter_context(patch("research.services.IntrinioClient", side_effect=factory))
            context.enter_context(
                patch("research.watchbar.PublicMarketClient", side_effect=public_factory)
            )
        with context:
            print(server.server_port, flush=True)
            server.serve_forever()


def main():
    from playwright.sync_api import sync_playwright

    output = ROOT / ".local/design-preview"
    output.mkdir(parents=True, exist_ok=True)
    with preview_application() as origin:
        with sync_playwright() as driver:
            browser = driver.chromium.launch(executable_path="/usr/bin/chromium", headless=True)
            try:
                context = browser.new_context(viewport={"width": 1440, "height": 1100})
                errors, requests, violations = [], [], []
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("request", lambda request: requests.append(request.url))
                page.add_init_script("""document.addEventListener('securitypolicyviolation',
                    e => console.error('CSP violation: ' + e.violatedDirective));""")
                page.on(
                    "console",
                    lambda message: (
                        violations.append(message.text)
                        if "CSP violation:" in message.text
                        else None
                    ),
                )
                base = origin + "/design/markets/"
                response = page.goto(base, wait_until="networkidle")
                assert response.status == 200
                assert page.get_by_text("Illustrative data only.", exact=False).is_visible()
                assert page.locator("[data-symbol]").count() == 38
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (
                    "Desktop overflow"
                )
                page.screenshot(path=str(output / "markets-dark-desktop.png"), full_page=True)

                initial_path = page.locator('[data-index="sp"] path').get_attribute("d")
                page.get_by_role("button", name="1M", exact=True).click()
                assert "-1.25%" in page.locator('[data-index="sp"] .index-change').inner_text()
                assert page.locator('[data-index="sp"] path').get_attribute("d") != initial_path
                page.get_by_role("button", name="1D", exact=True).click()
                tile = page.locator('[data-symbol="AAPL"]')
                tile.focus()
                page.keyboard.press("Enter")
                assert "Apple" in page.locator(".selection-name").inner_text()
                assert "194.32" in page.locator(".selection-price").inner_text()
                page.get_by_role("button", name="Sectors", exact=True).click()
                assert not tile.is_visible()
                assert page.locator(".sector-summary").first.is_visible()
                page.get_by_role("button", name="Companies", exact=True).click()

                page.get_by_role("combobox", name="Color theme").select_option("light")
                assert page.locator("html").get_attribute("data-theme") == "light"
                page.reload(wait_until="networkidle")
                assert page.get_by_role("combobox", name="Color theme").input_value() == "light"
                page.screenshot(path=str(output / "markets-light-desktop.png"), full_page=True)
                # Migrate the former System preference to a fixed explicit theme.
                page.evaluate("localStorage.setItem('portfoliolens-theme', 'system')")
                page.emulate_media(color_scheme="light")
                page.reload(wait_until="networkidle")
                assert page.get_by_role("combobox", name="Color theme").input_value() == "light"
                assert page.evaluate("localStorage.getItem('portfoliolens-theme')") == "light"
                page.emulate_media(color_scheme="dark")
                assert page.locator("html").get_attribute("data-theme") == "light"
                assert page.locator("#theme-select option").count() == 2

                page.get_by_role("button", name="Customize", exact=True).click()
                dialog = page.get_by_role("dialog")
                dialog.get_by_label("Bitcoin / USD").uncheck()
                dialog.get_by_role("button", name="Save preferences").click()
                assert not page.locator('[data-watch="btc"]').is_visible()
                page.reload(wait_until="networkidle")
                assert not page.locator('[data-watch="btc"]').is_visible()
                page.get_by_role("button", name="Customize", exact=True).click()
                dialog.get_by_label("Bitcoin / USD").check()
                dialog.get_by_role("button", name="Save preferences").click()
                page.get_by_role("combobox", name="Color theme").select_option("dark")
                for width, height in ((1024, 900), (768, 1024), (390, 844)):
                    page.set_viewport_size({"width": width, "height": height})
                    assert page.evaluate(
                        "document.documentElement.scrollWidth <= window.innerWidth"
                    ), f"Overflow at {width}px"
                    assert page.get_by_role("combobox", name="Color theme").is_visible()
                    if width == 390:
                        page.reload(wait_until="networkidle")
                        assert page.locator(".heatmap-grid.is-sector-view").is_visible()
                        page.screenshot(
                            path=str(output / "markets-dark-mobile.png"), full_page=True
                        )
                assert not errors, errors
                assert not violations, violations
                assert all(urlsplit(url).hostname == "127.0.0.1" for url in requests)
                print(
                    "Markets preview PASS: themes/legacy preference migration, period charts, "
                    "keyboard selection, sector view, watchbar persistence, CSP, "
                    "local requests only, and 1440/1024/768/390px layouts."
                )
                print(f"Screenshots: {output}")
            finally:
                browser.close()


if __name__ == "__main__":
    serve() if "--serve" in sys.argv else main()
