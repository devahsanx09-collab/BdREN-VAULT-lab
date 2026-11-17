"""Pages that belong to no single app: every screen of the web application, health check, robots.txt, CSRF error.

Each screen is its own URL (see apps/core/pages.py). They all render templates/base.html (side menu, top bar,
shared pop-ups and scripts) with the screen's own template in the content block.
"""
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie

from apps.devices.vendors import vendor_menu, vendor_meta

from .pages import BY_KEY, DEVICE_PAGE, HOME, menu_for, page_urls, url_of

ROLE_LABEL = {"admin": "Administrator", "operator": "Operator", "viewer": "Viewer"}


def _render_page(request, page, status=200, **extra):
    """base.html + the page's template, with the menu, breadcrumb and data the shared scripts need."""
    allowed = request.user.has_role(page.role)
    context = {
        "page": page,
        "menu": menu_for(request.user),
        "page_urls": page_urls(),
        "vmeta": vendor_meta(),
        "vendor_menu": vendor_menu(),      # Device type list in the Add / Edit device pop-ups
        "role_label": ROLE_LABEL.get(request.user.role, request.user.role),
        "session_idle_ms": settings.SESSION_MINUTES * 60 * 1000,
        "denied": not allowed,
        **extra,
    }
    return render(request, page.template if allowed else "errors/forbidden.html", context,
                  status=status if allowed else 403)


@login_required
def index(request):
    """/ opens the Dashboard."""
    return redirect(url_of(BY_KEY[HOME]))


@login_required
@ensure_csrf_cookie
def page_view(request, key):
    """One screen of the application (Dashboard, Device Inventory, Backups, ...)."""
    page = BY_KEY.get(key)
    if page is None:
        raise Http404
    return _render_page(request, page)


@login_required
@ensure_csrf_cookie
def device_page(request, pk):
    """One device's own backup page (/devices/<id>); the data is loaded by the page itself."""
    return _render_page(request, DEVICE_PAGE, device_id=pk)


def healthz(request):
    """Unauthenticated liveness probe for monitoring / load balancers (says nothing else about the server)."""
    return JsonResponse({"status": "ok"})


def robots_txt(request):
    """Private panel: ask every crawler to stay out (X-Robots-Tag on every response does the rest)."""
    return HttpResponse("User-agent: *\nDisallow: /\n", content_type="text/plain; charset=utf-8")


def csrf_failure(request, reason=""):
    if request.path.startswith("/api/"):
        return JsonResponse({"error": "Cross-site request blocked"}, status=403)
    return HttpResponseForbidden("Cross-site request blocked")
