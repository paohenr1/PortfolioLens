from django.urls import path

from ledger import correction_views, views

urlpatterns = [
    path("", views.history, name="ledger_history"),
    path("record/", views.entry_create, name="ledger_create"),
    path("corrections/", correction_views.audit, name="ledger_audit"),
    path("<uuid:target_id>/correct/", correction_views.correct, name="ledger_correct"),
    path("<uuid:target_id>/void/", correction_views.correct, {"void": True}, name="ledger_void"),
]
