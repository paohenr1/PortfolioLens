"""Browser-only application on its own temporary PostgreSQL database."""

import json
import os
import signal
import sys
import uuid
from contextlib import ExitStack
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, make_server


class QuietHandler(WSGIRequestHandler):
    def log_message(self, format, *args):
        pass


def interrupted(signum, frame):
    raise KeyboardInterrupt


def main():
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
    os.environ["DJANGO_ENV"] = "development"
    os.environ["DJANGO_DEBUG"] = "true"
    os.environ["DJANGO_ALLOWED_HOSTS"] = "127.0.0.1"

    import django
    import psycopg
    from django.conf import settings
    from psycopg import sql

    configured = settings.DATABASES["default"]
    live_market_data = os.environ.get("STOCK_MARKET_BROWSER_LIVE") == "1"
    watchlist_market_fixtures = os.environ.get("STOCK_WATCHLIST_MARKET_BROWSER_FIXTURES") == "1"
    ledger_fixtures = os.environ.get("STOCK_LEDGER_BROWSER_FIXTURES") == "1"
    live_request_count = 0
    maximum_live_requests = int(os.environ.get("STOCK_MARKET_BROWSER_MAX_REQUESTS", "32"))
    if not 1 <= maximum_live_requests <= 32:
        raise SystemExit("Live acceptance requires a request cap from 1 through 32.")
    if live_market_data and (ledger_fixtures or watchlist_market_fixtures):
        raise SystemExit("Live acceptance cannot use synthetic provider fixtures.")
    if configured["ENGINE"] != "django.db.backends.postgresql":
        raise SystemExit("Portfolio browser checks require the isolated PostgreSQL test settings.")
    params = {
        "host": configured["HOST"],
        "port": configured["PORT"],
        "user": configured["USER"],
        "password": configured["PASSWORD"],
        **configured["OPTIONS"],
    }
    database_name = "test_stock_browser_" + uuid.uuid4().hex
    with psycopg.connect(dbname="postgres", autocommit=True, **params) as control:
        control.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        try:
            configured["NAME"] = database_name
            if not live_market_data:
                settings.INTRINIO_API_KEY = ""
            django.setup()
            from django.contrib.staticfiles.handlers import StaticFilesHandler
            from django.core.management import call_command
            from django.core.wsgi import get_wsgi_application

            call_command("migrate", interactive=False, verbosity=0)
            application = StaticFilesHandler(get_wsgi_application())
            signal.signal(signal.SIGTERM, interrupted)
            with ExitStack() as stack:
                if live_market_data:
                    from unittest.mock import patch

                    from market_data.errors import ProviderError
                    from market_data.intrinio import IntrinioClient

                    original_request = IntrinioClient._request_json

                    def counted_request(client, path, params=None):
                        nonlocal live_request_count
                        if live_request_count >= maximum_live_requests:
                            raise ProviderError()
                        live_request_count += 1
                        return original_request(client, path, params)

                    # Observe real backend calls and enforce a test-only cost cap.
                    # This never replaces transport, credentials or shared quotas.
                    stack.enter_context(
                        patch.object(IntrinioClient, "_request_json", counted_request)
                    )
                if ledger_fixtures or watchlist_market_fixtures:
                    # Explicit test-only transport; normal startup never selects fixtures.
                    from unittest.mock import patch

                    import httpx

                    from market_data.intrinio import IntrinioClient
                    from tests.test_intrinio import TEST_KEY, fixture

                    settings.INTRINIO_API_KEY = TEST_KEY

                    def transport(request):
                        if request.url.path == "/securities/search":
                            return httpx.Response(200, json=fixture("security_search.json"))
                        if (
                            watchlist_market_fixtures
                            and request.url.path == "/securities/sec_fixture_primary/prices"
                        ):
                            from tests.watchlist_market_fixture import transport as market_transport

                            return market_transport(request)
                        if request.url.path == "/securities/sec_fixture_relationship":
                            return httpx.Response(
                                200, json=fixture("relationship_prices.json")["security"]
                            )
                        if request.url.path == "/securities/sec_fixture_benchmark":
                            return httpx.Response(
                                200, json=fixture("benchmark_prices.json")["security"]
                            )
                        if request.url.path == "/securities/sec_fixture_risk":
                            return httpx.Response(200, json=fixture("risk_prices.json")["security"])
                        if request.url.path == "/securities/sec_fixture_primary":
                            return httpx.Response(200, json=fixture("security_reference.json"))
                        if request.url.path in (
                            "/securities/sec_fixture_primary/prices",
                            "/securities/sec_fixture_risk/prices",
                            "/securities/sec_fixture_benchmark/prices",
                            "/securities/sec_fixture_relationship/prices",
                        ):
                            data = fixture(
                                "relationship_prices.json"
                                if "sec_fixture_relationship" in request.url.path
                                else "benchmark_prices.json"
                                if "sec_fixture_benchmark" in request.url.path
                                else "risk_prices.json"
                                if "sec_fixture_risk" in request.url.path
                                else "daily_prices.json"
                            )
                            data["stock_prices"] = [
                                item
                                for item in data["stock_prices"]
                                if request.url.params["start_date"]
                                <= item["date"]
                                <= request.url.params["end_date"]
                            ]
                            return httpx.Response(200, json=data)
                        return httpx.Response(404)

                    stack.enter_context(
                        patch(
                            "research.services.IntrinioClient",
                            side_effect=lambda key: IntrinioClient(
                                key, transport=httpx.MockTransport(transport)
                            ),
                        )
                    )
                server = stack.enter_context(
                    make_server("127.0.0.1", 0, application, handler_class=QuietHandler)
                )
                print(server.server_port, flush=True)
                try:
                    server.serve_forever()
                except KeyboardInterrupt:
                    pass
        finally:
            from django.db import connections

            connections.close_all()
            # Delete only the database generated and created by this process.
            control.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database_name))
            )
            if live_market_data:
                print(json.dumps({"live_request_count": live_request_count}), flush=True)


if __name__ == "__main__":
    main()
