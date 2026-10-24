from django.urls import path

from ledger import correction_views, picker_views, views

urlpatterns = [
    path("", views.history, name="ledger_history"),
    path("record/", views.entry_create, name="ledger_create"),
    path("instruments/search/", picker_views.instrument_search, name="ledger_instrument_search"),
    path("instruments/held/", picker_views.held_instruments, name="ledger_held_instruments"),
    path("corrections/", correction_views.audit, name="ledger_audit"),
    path("<uuid:target_id>/correct/", correction_views.correct, name="ledger_correct"),
    path("<uuid:target_id>/void/", correction_views.correct, {"void": True}, name="ledger_void"),
]
