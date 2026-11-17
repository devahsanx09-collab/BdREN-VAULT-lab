"""Monitoring - HTTP layer: /api/ping (ping column) and /api/dashboard (Dashboard numbers)."""
from django.http import JsonResponse

from apps.core.api import api

from . import selectors, services


@api(GET="viewer")
def ping_all(request):
    """Ping devices in parallel -> {device id: {up, ms}}. ?ids=1,2,3 pings only those (rows on screen)."""
    wanted = {int(x) for x in (request.GET.get("ids") or "").split(",") if x.strip().isdigit()}
    return JsonResponse(services.ping_devices(wanted))


@api(GET="viewer")
def dashboard(request):
    """Numbers for the Dashboard graphs: backups per day, uptime history, vendors, next scheduled run."""
    return JsonResponse(selectors.dashboard(show_internals=request.user.has_role("admin")))
