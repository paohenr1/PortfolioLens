from django.urls import include, path

from operations.health import live
from research.capital_return_views import capital_returns
from research.capitalization_views import market_capitalization
from research.design_preview import markets_preview
from research.growth_views import annual_growth
from research.multiple_views import annual_multiples
from research.trend_views import statement_trends
from research.views import financials, home, prices, search, security

urlpatterns = [
    path("health/live/", live, name="health_live"),
    path("", include("accounts.urls")),
    path("portfolios/", include("portfolios.urls")),
    path("watchlists/", include("watchlists.urls")),
    path("", home, name="home"),
    path("design/markets/", markets_preview, name="markets_preview"),
    path("search/", search, name="search"),
    path("stocks/<str:security_id>/", security, name="security"),
    path("stocks/<str:security_id>/prices/", prices, name="prices"),
    path("stocks/<str:security_id>/financials/", financials, name="financials"),
    path("stocks/<str:security_id>/returns-on-capital/", capital_returns, name="capital_returns"),
    path("stocks/<str:security_id>/growth/", annual_growth, name="annual_growth"),
    path("stocks/<str:security_id>/multiples/", annual_multiples, name="annual_multiples"),
    path(
        "stocks/<str:security_id>/market-cap/", market_capitalization, name="market_capitalization"
    ),
    path("stocks/<str:security_id>/trends/", statement_trends, name="statement_trends"),
]
