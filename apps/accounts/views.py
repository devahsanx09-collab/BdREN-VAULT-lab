"""Accounts - HTTP layer: sign-in / setup pages and the /api/me and /api/users endpoints.

Views read the request, call selectors (reads) or services (rules and changes), record the audit entry and
answer. They do not query the database themselves.
"""
from django.contrib.auth import login, logout, update_session_auth_hash
from django.conf import settings
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.backups.audit import record_audit, signin_summary
from apps.core.api import ApiError, api
from apps.core.utils import parse_json

from . import selectors, services

_BACKEND = "django.contrib.auth.backends.ModelBackend"


# Notices above the sign-in form, chosen by /login?reason=... (set by the app when it signs you out).
NOTICES = {
    "idle": "You were signed out after a period of inactivity. Sign in again to continue.",
    "signed-out": "You have signed out. Sign in again whenever you are ready.",
}


def _auth_page(request, **ctx):
    ctx.setdefault("notice", NOTICES.get(request.GET.get("reason", ""), ""))
    ctx.setdefault("next", _safe_next(request))
    ctx.setdefault("idle_minutes", settings.SESSION_MINUTES)
    return render(request, "accounts/auth.html", ctx)


def _safe_next(request):
    """The page to open after signing in (?next=/devices), only if it is a path on this site."""
    target = request.POST.get("next") or request.GET.get("next") or ""
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()},
                                                  require_https=request.is_secure()) and target.startswith("/"):
        return target
    return ""


def _is_local(request):
    """Only accept setup from a browser opened directly on the server.

    A reverse proxy on the same machine makes REMOTE_ADDR look like localhost for
    every remote visitor. Also validate the Host header so a public proxied request
    cannot use the proxy's loopback address to claim it is local.
    """
    import ipaddress
    from urllib.parse import urlsplit

    try:
        remote = ipaddress.ip_address(request.META.get("REMOTE_ADDR", ""))
        host = (urlsplit("//" + (request.get_host() or "")).hostname or "").lower()
    except (ValueError, TypeError):
        return False
    return remote.is_loopback and host in ("localhost", "127.0.0.1", "::1")


def setup(request):
    """Page: create the first administrator (only while there are no users).

    Security: until the first administrator exists, whoever opens this page owns the system. So it is
    only served to the server PC itself (http://127.0.0.1:8000/setup) unless DBMS_SETUP_FROM_ANYWHERE=1.
    """
    if selectors.any_user_exists():
        return redirect("login")
    if not settings.SETUP_FROM_ANYWHERE and not _is_local(request):
        return HttpResponseForbidden("First-time setup is only allowed on the server PC itself. "
                                     "Open http://127.0.0.1:8000/setup there, or run: python manage.py createsuperuser")
    error, username = "", ""
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        error = services.check_username(username) or services.check_password(password) or \
            ("Passwords do not match" if password != request.POST.get("confirm", "") else "")
        if not error:
            user = services.create_user(username, password, "admin")
            login(request, user, backend=_BACKEND)
            record_audit(request, "setup.first_admin", username, "First administrator created")
            return redirect("/")
    return _auth_page(request, title="Create administrator", setup=True, button="Create account",
                      sub="First-time setup. This account can manage everything.", error=error,
                      username=username)


def _browser(request):
    """'Chrome on Windows' from the User-Agent, for the sign-in history (best effort, never raises)."""
    ua = (request.META.get("HTTP_USER_AGENT") or "")[:400]
    browser = next((name for key, name in (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"),
                                           ("Chrome/", "Chrome"), ("Safari/", "Safari")) if key in ua), "")
    system = next((name for key, name in (("Windows", "Windows"), ("Android", "Android"), ("iPhone", "iPhone"),
                                          ("iPad", "iPad"), ("Mac OS", "macOS"), ("Linux", "Linux")) if key in ua), "")
    if browser and system:
        return f"{browser} on {system}"
    return browser or system or (ua[:60] if ua else "Unknown browser")


def login_view(request):
    """Page: sign in, with a lockout after 5 wrong passwords."""
    if not selectors.any_user_exists():
        return redirect("setup")
    if request.user.is_authenticated:
        return redirect(_safe_next(request) or "/")
    error, username = "", ""
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        ip = request.META.get("REMOTE_ADDR", "")
        if services.is_locked(ip, username):
            error = (f"Too many failed sign-in attempts. For your security, sign-in is paused for "
                     f"{services.LOCK_SECONDS // 60} minutes. Try again later.")
        else:
            user, ok = services.check_credentials(username, password)
            if ok and user.is_active:
                services.clear_failures(ip, username)
                login(request, user, backend=_BACKEND)
                # "Keep me signed in": the session survives closing the browser; idle sign-out still applies.
                request.session.set_expiry(settings.SESSION_MINUTES * 60 if request.POST.get("remember") else 0)
                record_audit(request, "login.success", user.username, f"Signed in · {_browser(request)}")
                return redirect(_safe_next(request) or "/")
            if ok:
                record_audit(request, "login.failed", user.username, f"Account is disabled · {_browser(request)}")
                error = "This account is disabled. Ask an administrator to enable it."
            else:
                services.register_failure(ip, username)
                record_audit(request, "login.failed", username[:100],
                             f"{'Wrong password' if user else 'Unknown username'} · {_browser(request)}")
                error = "The username or password is incorrect. Check both and try again."
    return _auth_page(request, title="Sign In", setup=False, button="Sign In",
                      sub="Access your account to manage configuration backups.", error=error,
                      username=username)


@require_POST
def logout_view(request):
    """API: end the session (works for every role)."""
    if request.user.is_authenticated:
        idle = request.headers.get("X-Requested-With") == "XMLHttpRequest" and request.GET.get("reason") == "idle"
        record_audit(request, "logout", request.user.username,
                     f"{'Signed out after inactivity' if idle else 'Signed out'} · {_browser(request)}")
    logout(request)
    return JsonResponse({"ok": True})


# ---------- API ----------
@api(GET="viewer")
def me(request):
    u = request.user
    return JsonResponse({"id": u.id, "username": u.username, "role": u.role})


@api(POST="viewer")
def change_my_password(request):
    """Change your own password; the user's other sessions are signed out."""
    data = parse_json(request)
    services.change_own_password(request.user, data.get("current"), data.get("new"))
    record_audit(request, "password.change", request.user.username, "Own password changed")
    update_session_auth_hash(request, request.user)      # keep this session, drop all others
    return JsonResponse({"ok": True})


@api(GET="admin", POST="admin")
def users(request):
    if request.method == "GET":
        return JsonResponse(selectors.user_rows(), safe=False)
    data = parse_json(request)
    username, role = (data.get("username") or "").strip(), data.get("role", "viewer")
    services.create_validated_user(username, data.get("password", ""), role)
    record_audit(request, "user.create", username, f"role={role}")
    return JsonResponse({"ok": True})


@api(GET="admin")
def signins(request):
    """Sign-in history for User Management: successful and failed sign-ins and sign-outs, newest first.
    ?account= (exact username), ?result=Signed in|Failed|Signed out, ?q= (account, IP or browser), ?limit= (max 2000)."""
    import ipaddress
    try:
        limit = min(max(int(request.GET.get("limit", "500")), 1), 2000)
    except ValueError:
        raise ApiError(400, "limit must be a number")
    rows = selectors.signin_history((request.GET.get("account") or "").strip(), request.GET.get("result") or "",
                                    (request.GET.get("q") or "").strip()[:100], limit)

    def loopback(a):
        try:
            return ipaddress.ip_address(a).is_loopback
        except ValueError:
            return False
    return JsonResponse({
        "rows": rows,
        "summary": signin_summary(),
        "ip_diag": _ip_diagnosis(request, loopback),       # why addresses may show 127.0.0.1, with the fix
    })


def _ip_diagnosis(request, loopback):
    """Why sign-ins may show 127.0.0.1, judged from THIS request (it came through the same path):
    ""                 the real address is visible - nothing to fix
    "setting_off"      DBMS_BEHIND_PROXY is not set, so the app does not trust nginx
    "header_missing"   the setting is on, but nginx does not send X-Forwarded-For
    "not_applied"      nginx sends the header, but the app was not started with `manage.py serve`
                       (or not restarted), so the header is not used"""
    if not loopback(request.META.get("REMOTE_ADDR", "") or "x"):
        return ""
    if not settings.BEHIND_PROXY:
        return "setting_off"
    return "not_applied" if request.META.get("HTTP_X_FORWARDED_FOR") else "header_missing"


@api(PUT="admin", DELETE="admin")
def user_detail(request, pk):
    target = selectors.get_user(pk)
    if request.method == "PUT":
        data = parse_json(request)
        services.update_user(target, request.user, data)
        record_audit(request, "user.update", target.username,
                     f"role={target.role}; active={target.is_active}; password_changed={bool(data.get('password'))}")
    else:
        name = target.username
        services.delete_user(target, request.user)
        record_audit(request, "user.delete", name, "User deleted")
    return JsonResponse({"ok": True})
