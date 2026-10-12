"""Show account creation only when the deployment explicitly permits it."""

from django.conf import settings


def registration_policy(request):
    return {"registration_available": settings.ALLOW_REGISTRATION}
