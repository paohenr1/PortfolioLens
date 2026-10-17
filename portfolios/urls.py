from django.urls import include, path

from ledger.daily_return_views import daily_returns
from ledger.performance_views import performance
from ledger.views import positions, valuation
from portfolios import views
from portfolios.holdings_views import holdings_preview

urlpatterns = [
    path("", views.portfolio_list, name="portfolio_list"),
    path("check-holdings/", holdings_preview, name="holdings_preview"),
    path("create/", views.portfolio_create, name="portfolio_create"),
    path("<uuid:portfolio_id>/", views.portfolio_detail, name="portfolio_detail"),
    path("<uuid:portfolio_id>/transactions/", include("ledger.urls")),
    path("<uuid:portfolio_id>/positions/", positions, name="portfolio_positions"),
    path("<uuid:portfolio_id>/valuation/", valuation, name="portfolio_valuation"),
    path("<uuid:portfolio_id>/performance/", performance, name="portfolio_performance"),
    path("<uuid:portfolio_id>/daily-returns/", daily_returns, name="portfolio_daily_returns"),
]
