"""RADIUS / AAA API (administrators only). The pages are templates/radius/users.html, nas.html and audit.html.

    /api/radius/users            GET list, POST create
    /api/radius/users/<name>     PUT change level / password, DELETE
    /api/radius/nas              GET list, POST add one or several (comma-separated IPs and names)
    /api/radius/nas/<id>         DELETE (restarts FreeRADIUS)
    /api/radius/audit            GET panel audit log + recent device logins
"""
import logging
import re
from functools import wraps

from django.db import Error as DatabaseError
from django.http import JsonResponse
from django.utils import timezone

from apps.core.api import ApiError, api
from apps.core.utils import DT_FORMAT, parse_json

from . import selectors as q
from . import services as s

logger = logging.getLogger("dbms")
USERNAME_RE = re.compile(r"^[A-Za-z0-9._@-]{1,64}$")
VENDOR_KEYS = {key for key, _ in s.VENDORS}


def radius_db(view):
    """A RADIUS database that is down or not configured becomes a clear message, not a bare 500."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except DatabaseError:
            logger.exception("RADIUS database error on %s %s", request.method, request.path)
            raise ApiError(503, "The RADIUS database is not reachable. Check the RADIUS_DB_* settings.")
    return wrapper


def _text(data, key, limit):
    value = data.get(key, "")
    value = value.strip() if isinstance(value, str) else ""
    if len(value) > limit:
        raise ApiError(400, f"{key.capitalize()} can be at most {limit} characters")
    return value


def _password(data, required):
    password = data.get("password", "")
    password = password if isinstance(password, str) else ""
    if not password and not required:
        return ""
    if len(password) < 8:
        raise ApiError(400, "Password needs at least 8 characters")
    if len(password) > 253:
        raise ApiError(400, "Password can be at most 253 characters")
    return password


def _level(data):
    level = data.get("level", "")
    if level not in s.PROFILES:
        raise ApiError(400, "Choose a valid access level")
    return level


def _devices(data):
    """Validated switch addresses from the form: [] = every switch."""
    raw = data.get("devices", [])
    if not isinstance(raw, list) or not all(isinstance(ip, str) for ip in raw):
        raise ApiError(400, "Choose the switches from the list")
    ips = sorted(set(raw), key=lambda ip: tuple(int(part) for part in ip.split(".")) if q.is_single_ip(ip) else ())
    known = {d["ip"] for d in q.selectable_devices() if d["single"]}
    unknown = [ip for ip in ips if ip not in known]
    if unknown:
        raise ApiError(400, f"Not a single-address RADIUS device: {unknown[0]}")
    return ips


def _types(data):
    """Validated device types from the form (free text, compared without case); [] = none picked."""
    raw = data.get("types", [])
    if not isinstance(raw, list) or not all(isinstance(t, str) for t in raw):
        raise ApiError(400, "Choose the device types from the list")
    out, seen = [], set()
    for t in raw:
        t = t.strip()
        if not t or t.lower() in seen:
            continue
        if len(t) > s.ROLE_MAX_LEN:
            raise ApiError(400, f"Device type can be at most {s.ROLE_MAX_LEN} characters")
        seen.add(t.lower())
        out.append(t)
    return out


def _when(value):
    if not value:
        return ""
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.strftime(DT_FORMAT)


def _scope(devices, types=()):
    if not devices and not types:
        return "all devices"
    parts = [f"type {t}" for t in types] + list(devices)
    return "only " + ", ".join(parts)


def _actor(request):
    return request.user.username, request.META.get("REMOTE_ADDR") or None


@api(GET="admin", POST="admin")
@radius_db
def users(request):
    if request.method == "GET":
        return JsonResponse({"users": q.list_users(request.GET.get("q", "").strip()), "levels": s.LEVELS,
                             "devices": q.selectable_devices(), "roles": q.distinct_roles(),
                             "limit_violations": q.limit_violations()})
    data = parse_json(request)
    username = _text(data, "username", 64)
    if not USERNAME_RE.match(username) or not username.strip("."):
        raise ApiError(400, "Username: letters, digits and . _ @ - only (1-64 characters)")
    password, level, devices, types = _password(data, required=True), _level(data), _devices(data), _types(data)
    if q.user_exists(username):
        raise ApiError(409, "A RADIUS user with this name already exists")
    s.create_user(username, password, level, devices, types)
    actor, ip = _actor(request)
    s.audit(actor, "user.create", username, f"{level}; {_scope(devices, types)}", ip)
    return JsonResponse({"username": username, "level": level, "devices": devices, "types": types}, status=201)


@api(PUT="admin", DELETE="admin")
@radius_db
def user_detail(request, username):
    if not q.user_exists(username):
        raise ApiError(404, "RADIUS user not found")
    actor, ip = _actor(request)
    if request.method == "DELETE":
        s.delete_user(username)
        s.audit(actor, "user.delete", username, "", ip)
        return JsonResponse({"ok": True})
    data = parse_json(request)
    level, password = _level(data), _password(data, required=False)
    # both absent = keep the current access; otherwise the form sends both
    access = "devices" in data or "types" in data
    devices = _devices(data) if access else None
    types = _types(data) if access else None
    s.update_user(username, level, password or None, devices, types)
    detail = level + (f"; {_scope(devices, types)}" if access else "") + (" +password" if password else "")
    s.audit(actor, "user.update", username, detail, ip)
    return JsonResponse({"username": username, "level": level})


@api(GET="admin", POST="admin")
@radius_db
def nas(request):
    if request.method == "GET":
        # Shared secrets are NOT part of the list: one is sent only when asked for (nas_secret below).
        return JsonResponse({"devices": q.nas_rows(), "vendors": [{"key": k, "label": v} for k, v in s.VENDORS],
                             "roles": q.distinct_roles(),
                             "reload_ok": s.reload_permission_ok()})
    # One device or several: "nasname" and "name" may be comma-separated lists in the same order.
    data = parse_json(request)
    result = s.add_nas_devices(_text(data, "nasname", 6000), _text(data, "name", 8000), data.get("vendor", ""),
                               _text(data, "secret", 60), _text(data, "description", 200),
                               _text(data, "role", s.ROLE_MAX_LEN))
    actor, ip = _actor(request)
    for d in result["added"]:
        s.audit(actor, "nas.create", d["nasname"], data.get("vendor", ""), ip)
    if not result["added"]:
        reasons = "; ".join(f"{x['nasname']}: {x['reason']}" for x in result["skipped"][:5])
        raise ApiError(409, f"Nothing was added. {reasons}")
    first = result["added"][0]
    return JsonResponse({**result, "id": first["id"]}, status=201)


@api(PATCH="admin", DELETE="admin")
@radius_db
def nas_detail(request, pk):
    device = q.get_nas(pk)
    actor, ip = _actor(request)
    if request.method == "PATCH":
        # Change the vendor and/or the network role; either key may be sent on its own.
        # Vendor takes effect on the next login: the FreeRADIUS policies read nas.type on every request,
        # so no restart is needed (e.g. "Huawei (levels 0-3)"). Role is a VAULT-only grouping.
        data = parse_json(request)
        changed = []
        if "vendor" in data:
            vendor = data.get("vendor", "")
            if vendor not in VENDOR_KEYS:
                raise ApiError(400, "Choose a valid device type")
            old = device.type
            s.update_nas_type(device, vendor)
            changed.append(f"type {old} -> {vendor}")
        if "role" in data:
            role = s.update_nas_role(device, _text(data, "role", s.ROLE_MAX_LEN))
            changed.append(f"role -> {role}")
        if not changed:
            raise ApiError(400, "Nothing to change")
        s.audit(actor, "nas.update", device.nasname, "; ".join(changed), ip)
        return JsonResponse({"ok": True})
    s.audit(actor, "nas.delete", device.nasname, "", ip)
    return JsonResponse({"ok": True, "reloaded": s.delete_nas(device)})


@api(POST="admin")
@radius_db
def nas_secret(request, pk):
    """Show ONE shared secret to an administrator who asked for it; the request is written to the audit log."""
    device = q.get_nas(pk)
    actor, ip = _actor(request)
    s.audit(actor, "nas.secret.view", device.nasname, "", ip)
    response = JsonResponse({"secret": device.secret})
    response["Cache-Control"] = "no-store, private"
    return response


@api(GET="admin")
@radius_db
def audit(request):
    events = [{"ts": _when(e.created_at), "actor": e.actor, "action": e.action, "target": e.target,
               "detail": e.detail, "ip": e.ip or ""} for e in q.admin_events(500)]
    logins, logging_on = q.recent_logins(q=request.GET.get("q", ""), limit=500)
    for row in logins:
        row["ts"] = _when(row.pop("authdate"))
    return JsonResponse({"events": events, "logins": logins, "device_logging": logging_on})
