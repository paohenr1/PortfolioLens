"""Process-only liveness: no database/provider query that keeps a free tier awake."""

from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe


@never_cache
@require_safe
def live(request):
    return JsonResponse({"status": "alive"})
