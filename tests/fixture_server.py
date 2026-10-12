"""Test-only loopback WSGI server; never included in application startup settings."""

import os
import sys
from pathlib import Path
from unittest.mock import patch
from wsgiref.simple_server import make_server


def main(*, statement_transport=None, price_transport=None, capitalization_transport=None):
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
    os.environ["DJANGO_ENV"] = "development"
    os.environ["DJANGO_DEBUG"] = "true"
    os.environ["DJANGO_ALLOWED_HOSTS"] = "127.0.0.1"

    import django

    django.setup()

    import httpx
    from django.contrib.staticfiles.handlers import StaticFilesHandler
    from django.core.wsgi import get_wsgi_application
    from django.test import override_settings

    from market_data.intrinio import IntrinioClient
    from tests.test_fundamentals import fixture_transport
    from tests.test_intrinio import TEST_KEY, fixture

    def transport(request):
        if capitalization_transport is not None and (
            request.url.path == "/data_tags/marketcap"
            or request.url.path.endswith("/historical_data/marketcap")
        ):
            return capitalization_transport(request)
        if price_transport is not None and request.url.path.endswith("/prices"):
            return price_transport(request)
        if statement_transport is not None and (
            "/fundamentals/lookup/" in request.url.path
            or request.url.path.endswith("/standardized_financials")
        ):
            return statement_transport(request)
        if request.url.path == "/securities/sec_fixture_primary/prices":
            prices = fixture("daily_prices.json")
            start = request.url.params.get("start_date")
            if start == "2020-02-01":
                prices["stock_prices"] = []
            elif start == "2020-03-01":
                return httpx.Response(429, headers={"Retry-After": "60"})
            elif start == "2020-04-01":
                return httpx.Response(403, text=TEST_KEY)
            return httpx.Response(200, json=prices)
        if request.url.path == "/securities/search":
            query = request.url.params.get("query")
            if query == "fixture-empty":
                return httpx.Response(200, json={"securities": []})
            if query == "fixture-rate-limit":
                return httpx.Response(429, headers={"Retry-After": "60"})
            if query == "fixture-auth-error":
                return httpx.Response(401, text=TEST_KEY)
            return httpx.Response(200, json=fixture("security_search.json"))
        if request.url.path == "/securities/sec_fixture_primary":
            return httpx.Response(200, json=fixture("security_reference.json"))
        if "/fundamentals/lookup/" in request.url.path:
            year = request.url.path.rsplit("/", 2)[-2]
            if year == "2017":
                return httpx.Response(404)
            if year == "2016":
                return httpx.Response(403, text=TEST_KEY)
            if year == "2015":
                return httpx.Response(429, headers={"Retry-After": "60"})
            return fixture_transport(request)
        if request.url.path.endswith("/standardized_financials"):
            response = fixture_transport(request)
            data = response.json()
            if data["fundamental"]["fiscal_year"] == 2018:
                data["standardized_financials"] = []
            return httpx.Response(200, json=data)
        return httpx.Response(404)

    def provider(key):
        return IntrinioClient(key, transport=httpx.MockTransport(transport))

    with override_settings(INTRINIO_API_KEY=TEST_KEY):
        with patch("research.services.IntrinioClient", side_effect=provider):
            application = StaticFilesHandler(get_wsgi_application())
            with make_server("127.0.0.1", 0, application) as server:
                print(server.server_port, flush=True)
                server.serve_forever()


if __name__ == "__main__":
    main()
