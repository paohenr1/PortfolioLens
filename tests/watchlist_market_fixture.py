"""Invented exact-date market scenarios, selected only by the browser-test server."""


def transport(request):
    import httpx

    from tests.test_watchlist_market import daily_transport

    day = request.url.params["start_date"]
    if day == "2020-01-10":
        return httpx.Response(429, headers={"Retry-After": "37"})
    if day == "2020-01-13":
        return httpx.Response(403)
    payload = daily_transport(request).json()
    if day == "2020-01-03":
        payload["stock_prices"][0]["adj_close"] = None
        payload["stock_prices"][0]["adj_volume"] = None
    elif day == "2020-01-06":
        payload["stock_prices"] = []
    elif day == "2020-01-07":
        payload["stock_prices"][0]["intraperiod"] = None
    elif day == "2020-01-08":
        payload["next_page"] = "fixture_cursor"
    elif day == "2020-01-09":
        payload["stock_prices"][0]["close"] = 0
        payload["stock_prices"][0]["volume"] = 0
    return httpx.Response(200, json=payload)
