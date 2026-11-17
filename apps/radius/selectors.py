"""RADIUS / AAA - read layer: RADIUS users, their devices, NAS clients, logins and admin events.

Reads the FreeRADIUS database (the `radius` connection, see router.py). Selectors never change data.
"""
import ipaddress
import logging
import re

from apps.core.api import ApiError

from .models import NO_DEVICE, ROLE_SUGGESTIONS, AuditLog, Nas, NasRole, RadCheck, RadUserGroup, UserDevice, UserGrant
from .router import DB

logger = logging.getLogger("dbms")
PASSWORD_ATTRS = ("Cleartext-Password", "SSHA2-256-Password")
LEGACY_ATTR = "NAS-IP-Address"
LEGACY_OP = "=~"


# ---- Recent device logins (Authentication Audit page) ----------------------------------------------
# FreeRADIUS's standard radpostauth table stores only username, reply and time - NOT the device the login
# came from. deploy/radius/enable_login_log.sh adds two columns (nasipaddress, nasidentifier) and makes
# FreeRADIUS fill them. Until it has run, logins are still listed, only without the device.
_LOGIN_COLS = {"at": 0.0, "cols": set(), "offset": 0}


def pattern_devices(value):
    """The IPv4 addresses inside a legacy "^(10[.]0[.]0[.]1|...)$" radcheck value; anything else gives []."""
    match = re.fullmatch(r"\^\((.*)\)\$", value or "")
    if not match:
        return []
    ips = [part.replace("[.]", ".") for part in match.group(1).split("|")]
    return ips if all(is_single_ip(ip) for ip in ips) else []


def is_single_ip(value):
    try:
        return ipaddress.ip_address(value).version == 4
    except ValueError:
        return False


def user_devices():
    """{username: [ip, ...]}: the addresses FreeRADIUS lets each limited user log in on (dbms_user_nas)."""
    limits = {}
    for name, ip in UserDevice.objects.order_by("id").values_list("username", "nasname"):
        if ip != NO_DEVICE:
            limits.setdefault(name, []).append(ip)
        else:
            limits.setdefault(name, [])
    return limits


def user_grants():
    """{username: {"types": [...], "devices": [...]}}: what the administrator chose for each user.
    Users saved before device types existed have no grant rows; their dbms_user_nas addresses are
    their device grants (see access_of)."""
    grants = {}
    for name, kind, value in UserGrant.objects.order_by("id").values_list("username", "kind", "value"):
        g = grants.setdefault(name, {"types": [], "devices": []})
        g["types" if kind == UserGrant.TYPE else "devices"].append(value)
    return grants


def access_of(username, grants=None, limits=None):
    """{"types": [...], "devices": [...]} for one user; both empty = every device."""
    grants = user_grants() if grants is None else grants
    if username in grants:
        return grants[username]
    limits = user_devices() if limits is None else limits
    return {"types": [], "devices": list(limits.get(username, []))}


def usernames_with_type_grants():
    return sorted(set(UserGrant.objects.filter(kind=UserGrant.TYPE).values_list("username", flat=True)))


def nas_by_role():
    """{role in lower case: [single-address device, ...]}; a device with no role set counts as "Other"."""
    roles = roles_by_nasname()
    out = {}
    for nasname in Nas.objects.values_list("nasname", flat=True):
        if is_single_ip(nasname):
            out.setdefault(roles.get(nasname, "Other").lower(), []).append(nasname)
    return out


def user_exists(username):
    return RadCheck.objects.filter(username=username).exists()


def list_users(query=""):
    names = RadCheck.objects.filter(attribute__in=PASSWORD_ATTRS)
    if query:
        names = names.filter(username__icontains=query)
    names = sorted(set(names.values_list("username", flat=True)), key=str.lower)
    groups = dict(RadUserGroup.objects.values_list("username", "groupname"))
    limits, grants = user_devices(), user_grants()
    legacy = dict(RadCheck.objects.filter(attribute=LEGACY_ATTR, op=LEGACY_OP).values_list("username", "value"))
    out = []
    for n in names:
        access = access_of(n, grants, limits)
        out.append({"username": n, "level": groups.get(n, "-"), "types": access["types"],
                    "devices": access["devices"] or ([] if access["types"] else pattern_devices(legacy.get(n, ""))),
                    # every address the user can log in on right now (types expanded); [] with types = none yet
                    "effective": limits.get(n, [])})
    return out


def roles_by_nasname():
    """{nasname: role} for every NAS client that has a network role set."""
    return dict(NasRole.objects.values_list("nasname", "role"))


def distinct_roles():
    """Device-type suggestions for the drop-down: the built-in starting list plus any custom label an
    administrator has already typed in, so it is offered again instead of being retyped."""
    out, seen = list(ROLE_SUGGESTIONS), {r.lower() for r in ROLE_SUGGESTIONS}
    for role in sorted(set(NasRole.objects.values_list("role", flat=True)), key=str.lower):
        if role and role.lower() not in seen:           # "access switch" and "Access switch" are one type
            seen.add(role.lower())
            out.append(role)
    return out


def canonical_role(role):
    """The existing spelling of a device type when there is one (compared without case), otherwise the
    text as typed with a capital first letter - so one type never appears twice in different cases."""
    for known in distinct_roles():
        if known.lower() == role.lower():
            return known
    return role[:1].upper() + role[1:]


def selectable_devices():
    """Devices for the "Selected switches" list. Network entries (10.0.0.0/24) cannot be picked one by one."""
    roles = roles_by_nasname()
    return [{"name": d.shortname, "ip": d.nasname, "single": is_single_ip(d.nasname),
             "role": roles.get(d.nasname, "Other")}
            for d in Nas.objects.order_by("shortname")]


def _login_columns():
    import time
    from django.db import connections
    if time.monotonic() - _LOGIN_COLS["at"] > 300:          # re-checked every 5 minutes (after running the script)
        conn = connections[DB]
        with conn.cursor() as cur:
            cols = {c.name.lower() for c in conn.introspection.get_table_description(cur, "radpostauth")}
            # FreeRADIUS writes authdate in the SERVER's local clock; MySQL NOW() uses the same clock,
            # so NOW() - UTC_TIMESTAMP() is the offset needed to show the right Bangladesh time.
            offset = 0
            try:
                cur.execute("SELECT TIMESTAMPDIFF(SECOND, UTC_TIMESTAMP(), NOW())")
                offset = int(cur.fetchone()[0] or 0)
            except Exception:
                pass
        _LOGIN_COLS.update(at=time.monotonic(), cols=cols, offset=offset)
    return _LOGIN_COLS["cols"]


def recent_logins(q="", limit=500):
    """Newest logins first: username, result, time and - when recorded - the device (IP, name).
    `q` matches the username, the device IP, or a device name from NAS Clients / Device Inventory.
    Returns (rows, device_logging_enabled)."""
    from django.db import connections
    from apps.devices import selectors as devices
    cols = _login_columns()
    has_ip, has_id = "nasipaddress" in cols, "nasidentifier" in cols
    names = {}                                                  # device IP -> readable name
    names.update(devices.names_by_ip())                         # inventory names first ...
    for nasname, short in Nas.objects.values_list("nasname", "shortname"):   # ... RADIUS NAS names win
        if short:
            names[nasname] = short
    where, params = [], []
    q = (q or "").strip()[:64]
    if q:
        ql = q.lower()
        parts, like = ["username LIKE %s"], f"%{q}%"
        params.append(like)
        if has_ip:
            parts.append("nasipaddress LIKE %s")
            params.append(like)
            ips = [ip for ip, n in names.items() if ql in n.lower()][:200]
            if ips:
                parts.append("nasipaddress IN (" + ",".join(["%s"] * len(ips)) + ")")
                params += ips
        if has_id:
            parts.append("nasidentifier LIKE %s")
            params.append(like)
        where.append("(" + " OR ".join(parts) + ")")
    sql = ("SELECT username, reply, authdate, " + ("nasipaddress" if has_ip else "''") + ", "
           + ("nasidentifier" if has_id else "''") + " FROM radpostauth"
           + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id DESC LIMIT %s")
    params.append(max(1, min(int(limit), 2000)))
    with connections[DB].cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    from datetime import timedelta, timezone as dt_tz
    shift = timedelta(seconds=_LOGIN_COLS.get("offset", 0))
    as_utc = lambda t: (t - shift).replace(tzinfo=dt_tz.utc) if t is not None and t.tzinfo is None else t
    out = [{"username": u, "reply": r or "", "authdate": as_utc(t), "nas_ip": ip or "", "nas_id": nid or "",
            "device": names.get(ip or "", "") or (nid or "")} for u, r, t, ip, nid in rows]
    return out, has_ip


def limit_violations(hours=24):
    """Logins FreeRADIUS ACCEPTED on a device outside the user's allowed list, in the last `hours`.
    Any row means the per-device limit is not enforced (dbms_device_limit policy missing from
    authorize { }) or a switch sends its requests from an address that is not the one in NAS Clients.
    Needs the device columns of radpostauth (deploy/radius/enable_login_log.sh); [] without them."""
    from django.db import connections
    try:
        if "nasipaddress" not in _login_columns():
            return []
        sql = ("SELECT p.username, p.nasipaddress, MAX(p.authdate), COUNT(*) FROM radpostauth p "
               "WHERE p.reply = 'Access-Accept' AND p.nasipaddress <> '' "
               "AND p.authdate >= NOW() - INTERVAL %s HOUR "
               "AND EXISTS (SELECT 1 FROM dbms_user_nas a WHERE a.username = p.username) "
               "AND NOT EXISTS (SELECT 1 FROM dbms_user_nas d WHERE d.username = p.username AND d.nasname = p.nasipaddress) "
               "GROUP BY p.username, p.nasipaddress "
               # already fixed: FreeRADIUS has REFUSED this user on this device after the last accepted login
               "HAVING MAX(p.id) > COALESCE((SELECT MAX(r.id) FROM radpostauth r WHERE r.username = p.username "
               "AND r.nasipaddress = p.nasipaddress AND r.reply = 'Access-Reject'), 0) "
               "ORDER BY MAX(p.authdate) DESC LIMIT 20")
        with connections[DB].cursor() as cur:
            cur.execute(sql, [int(hours)])
            rows = cur.fetchall()
    except Exception:
        logger.warning("Could not check per-device login limits", exc_info=True)
        return []
    names = {n: s for n, s in Nas.objects.values_list("nasname", "shortname")}
    return [{"username": u, "ip": ip, "device": names.get(ip, ""), "count": n,
             "last": t.strftime("%d %b %Y, %I:%M %p") if hasattr(t, "strftime") else str(t or "")}
            for u, ip, t, n in rows]


def nas_rows():
    """NAS Clients list. Shared secrets are NOT included: one is sent only when asked for (get_nas)."""
    roles = roles_by_nasname()
    return [{"id": d.pk, "name": d.shortname, "nasname": d.nasname, "vendor": d.type,
             "role": roles.get(d.nasname, "Other"), "description": d.description or ""}
            for d in Nas.objects.order_by("shortname")]


def get_nas(pk):
    device = Nas.objects.filter(pk=pk).first()
    if device is None:
        raise ApiError(404, "Device not found")
    return device


def nas_exists(nasname):
    return Nas.objects.filter(nasname=nasname).exists()


def admin_events(limit=500):
    """Changes made on the RADIUS pages, newest first."""
    return AuditLog.objects.all()[:limit]
