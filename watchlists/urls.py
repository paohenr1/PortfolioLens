from django.urls import path

from watchlists import views
from watchlists.market_views import market_information, preferences

urlpatterns = [
    path("", views.watchlist_list, name="watchlist_list"),
    path("create/", views.watchlist_create, name="watchlist_create"),
    path("add/", views.instrument_add, name="watchlist_choose"),
    path("<uuid:watchlist_id>/", views.watchlist_detail, name="watchlist_detail"),
    path("<uuid:watchlist_id>/add/", views.instrument_add, name="watchlist_add"),
    path("<uuid:watchlist_id>/preferences/", preferences, name="watchlist_preferences"),
    path("<uuid:watchlist_id>/market/", market_information, name="watchlist_market"),
    path(
        "<uuid:watchlist_id>/items/<uuid:item_id>/remove/",
        views.instrument_remove,
        name="watchlist_remove",
    ),
]
