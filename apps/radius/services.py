"""RADIUS / AAA - business layer: users, access levels, devices (NAS) and the FreeRADIUS restart.

Every change to the `radius` database (see router.py), the same one FreeRADIUS reads. Reads are in selectors.py.
"""
import base64
import hashlib
import logging
import os
import secrets
import shlex
import subprocess
import threading

from django.conf import settings
from django.db import transaction

from . import selectors
from .models import (NO_DEVICE, ROLE_MAX_LEN, ROLE_SUGGESTIONS, AuditLog, Nas, NasRole, RadCheck, RadGroupReply, RadUserGroup,
                     UserDevice, UserGrant, clean_role)
from .router import DB
from .selectors import LEGACY_ATTR, LEGACY_OP, PASSWORD_ATTRS, is_single_ip, pattern_devices

logger = logging.getLogger("dbms")

# "This user may log in on these switches only" is one row per switch in dbms_user_nas.
# FreeRADIUS checks it with the dbms_device_limit policy (deploy/radius/dbms_device_limit), which
# compares the rows with the address the request came from. No rows = every switch.
#
# Earlier builds wrote a radcheck row "NAS-IP-Address =~ ^(...)$" instead. FreeRADIUS 3 cannot read a
# regular expression for an IP-address attribute from SQL ("Error parsing value"), so that row made
# every login of the user fail, on every switch. _set_access() removes it; radius_init converts it.
# (LEGACY_ATTR / LEGACY_OP are defined in selectors.py.)


# access level -> vendor attributes returned to the device.
# ":=" REPLACES a value set earlier in the request: a FreeRADIUS "users"/"authorize" DEFAULT entry or
# another module that already put e.g. Huawei-Exec-Privilege = 15 in the reply would otherwise win, because
# "=" only adds an attribute that is not there yet (a read-only user then got super-admin on Huawei).
# Cisco-AVPair stays "+=": it is multi-valued and a device may need several pairs.
PROFILES = {
    "super-admin": [
        ("Cisco-AVPair", "+=", "shell:priv-lvl=15"),
        ("Huawei-Exec-Privilege", ":=", "15"),
        ("Mikrotik-Group", ":=", "full"),
        ("Juniper-Local-User-Name", ":=", "super-user"),
        ("Fortinet-Group-Name", ":=", "super_admin"),
    ],
    "read-write": [
        ("Cisco-AVPair", "+=", "shell:priv-lvl=7"),
        # Huawei: 0 visit, 1 monitor, 2 configuration, 3 management (3 = almost everything), so
        # "limited changes" is level 2. Super-admin 15 is capped to 3 on switches whose NAS Clients type
        # is "Huawei (levels 0-3)" by the dbms_huawei_levels FreeRADIUS policy.
        ("Huawei-Exec-Privilege", ":=", "2"),
        ("Mikrotik-Group", ":=", "write"),
        ("Juniper-Local-User-Name", ":=", "operator"),
        ("Fortinet-Group-Name", ":=", "rw_admin"),
    ],
    "read-only": [
        ("Cisco-AVPair", "+=", "shell:priv-lvl=1"),
        ("Huawei-Exec-Privilege", ":=", "1"),
        ("Mikrotik-Group", ":=", "read"),
        ("Juniper-Local-User-Name", ":=", "read-only"),
        ("Fortinet-Group-Name", ":=", "ro_admin"),
    ],
}

LEVELS = list(PROFILES)

VENDORS = [("cisco", "Cisco"), ("huawei", "Huawei (levels 0-15)"), ("huawei-3", "Huawei (levels 0-3 only)"),
           ("mikrotik", "MikroTik"),
           ("juniper", "Juniper"), ("fortinet", "Fortinet"), ("bdcom", "BDCOM"), ("vsol", "V-SOL"),
           ("other", "Other")]

# ROLE_SUGGESTIONS / ROLE_MAX_LEN / clean_role live in models.py (selectors.distinct_roles() needs them
# too, and selectors must not import services - see apps/core/architecture.py).


def audit(actor, action, target="", detail="", ip=None):
    """Write one audit line. The action itself has already happened, so a failed write is only logged."""
    try:
        AuditLog.objects.create(actor=actor[:150], action=action[:40], target=target[:200],
                                detail=detail[:300], ip=ip or None)
    except Exception:
        logger.exception("Could not write the RADIUS audit line %s %s", action, target)


def hash_password(password):
    """(attribute, value) to store for a password, according to RADIUS_PASSWORD_MODE.

    "cleartext" (default, unchanged from the original RADIUS Admin) or "ssha2": salted SHA-256 in the
    form FreeRADIUS expects for SSHA2-256-Password, base64(digest + salt).
    """
    if settings.RADIUS_PASSWORD_MODE == "ssha2":
        salt = os.urandom(16)
        digest = hashlib.sha256(password.encode("utf-8") + salt).digest()
        return "SSHA2-256-Password", base64.b64encode(digest + salt).decode("ascii")
    return "Cleartext-Password", password


def seed_groups():
    """Create/refresh the group reply attributes from PROFILES."""
    with transaction.atomic(using=DB):
        RadGroupReply.objects.filter(groupname__in=PROFILES.keys()).delete()
        for group, attrs in PROFILES.items():
            for attr, op, val in attrs:
                RadGroupReply.objects.create(groupname=group, attribute=attr, op=op, value=val)


def _set_password(username, password):
    RadCheck.objects.filter(username=username, attribute__in=PASSWORD_ATTRS).delete()
    attr, val = hash_password(password)
    RadCheck.objects.create(username=username, attribute=attr, op=":=", value=val)


def _effective_ips(devices, types, by_role):
    """The addresses a user may log in on: the devices picked one by one plus every device of the picked types."""
    ips = list(devices)
    for t in types:
        ips += by_role.get(t.lower(), [])
    return list(dict.fromkeys(ips))


def _write_effective(username, access, by_role):
    """Rewrite the user's dbms_user_nas rows (what FreeRADIUS checks) from their grants."""
    UserDevice.objects.filter(username=username).delete()
    if not access["devices"] and not access["types"]:
        return                                      # no rows = every device
    ips = _effective_ips(access["devices"], access["types"], by_role) or [NO_DEVICE]
    UserDevice.objects.bulk_create([UserDevice(username=username, nasname=ip) for ip in ips])


def _set_access(username, devices, types):
    """Limit the user to these device types and/or addresses; both empty allows every device again.
    A type also covers devices of that type added later (resync_type_grants)."""
    RadCheck.objects.filter(username=username, attribute=LEGACY_ATTR, op=LEGACY_OP).delete()
    UserGrant.objects.filter(username=username).delete()
    access = {"devices": list(dict.fromkeys(devices)),
              "types": list(dict.fromkeys(selectors.canonical_role(t) for t in types))}
    UserGrant.objects.bulk_create(
        [UserGrant(username=username, kind=UserGrant.TYPE, value=t) for t in access["types"]]
        + [UserGrant(username=username, kind=UserGrant.DEVICE, value=ip) for ip in access["devices"]])
    _write_effective(username, access, selectors.nas_by_role())


def resync_type_grants():
    """After a device is added, removed or changes type: recalculate every user who was given access by type,
    so e.g. a new access switch is usable at once by everyone allowed on "Access switch". No restart:
    FreeRADIUS reads dbms_user_nas on every login."""
    names = selectors.usernames_with_type_grants()
    if not names:
        return
    by_role, grants = selectors.nas_by_role(), selectors.user_grants()
    with transaction.atomic(using=DB):
        for name in names:
            _write_effective(name, grants[name], by_role)


def normalize_roles():
    """One spelling per device type: rows saved as "access switch" become "Access switch" (radius_init).
    Returns how many rows were changed."""
    canon = {r.lower(): r for r in ROLE_SUGGESTIONS}
    stored = set(NasRole.objects.values_list("role", flat=True)) | set(
        UserGrant.objects.filter(kind=UserGrant.TYPE).values_list("value", flat=True))
    for role in sorted(stored):
        canon.setdefault(role.lower(), role[:1].upper() + role[1:])
    changed = 0
    with transaction.atomic(using=DB):
        for role in stored:
            want = canon[role.lower()]
            if want == role:
                continue
            changed += NasRole.objects.filter(role=role).update(role=want)
            for grant in UserGrant.objects.filter(kind=UserGrant.TYPE, value=role):
                if UserGrant.objects.filter(username=grant.username, kind=UserGrant.TYPE, value=want).exists():
                    grant.delete()
                else:
                    grant.value = want
                    grant.save(update_fields=["value"])
                changed += 1
        if changed:
            resync_type_grants()
    return changed


def convert_legacy_limits():
    """Move the old "NAS-IP-Address =~" radcheck rows into dbms_user_nas. Returns the usernames converted."""
    done = []
    with transaction.atomic(using=DB):
        for row in RadCheck.objects.filter(attribute=LEGACY_ATTR, op=LEGACY_OP):
            ips = pattern_devices(row.value)
            if ips and not UserDevice.objects.filter(username=row.username).exists():
                UserDevice.objects.bulk_create([UserDevice(username=row.username, nasname=ip) for ip in ips])
            row.delete()
            done.append(row.username)
    return done


def create_user(username, password, level, devices=(), types=()):
    with transaction.atomic(using=DB):
        _set_password(username, password)
        _set_access(username, list(devices), list(types))
        RadUserGroup.objects.create(username=username, groupname=level, priority=1)


def update_user(username, level=None, password=None, devices=None, types=None):
    """`devices` / `types`: both None = leave access as it is; otherwise the new access
    (both empty = every device)."""
    with transaction.atomic(using=DB):
        if password:
            _set_password(username, password)
        if devices is not None or types is not None:
            _set_access(username, list(devices or []), list(types or []))
        if level:
            RadUserGroup.objects.filter(username=username).delete()
            RadUserGroup.objects.create(username=username, groupname=level, priority=1)


def delete_user(username):
    with transaction.atomic(using=DB):
        RadCheck.objects.filter(username=username).delete()
        RadUserGroup.objects.filter(username=username).delete()
        UserDevice.objects.filter(username=username).delete()
        UserGrant.objects.filter(username=username).delete()


def generate_secret():
    return secrets.token_urlsafe(18)[:24]


def create_nas(nasname, shortname, vendor, secret, description=""):
    return Nas.objects.create(nasname=nasname, shortname=shortname, type=vendor,
                              secret=secret, description=description)


def _checked_role(role):
    from apps.core.api import ApiError
    if len(role) > ROLE_MAX_LEN:
        raise ApiError(400, f"Device type can be at most {ROLE_MAX_LEN} characters")
    return selectors.canonical_role(clean_role(role))


def set_nas_roles(nasnames, role):
    """Set the network role of these NAS clients (replacing any role they already had)."""
    NasRole.objects.filter(nasname__in=nasnames).delete()
    NasRole.objects.bulk_create([NasRole(nasname=n, role=role) for n in nasnames])


def update_nas_role(device, role):
    """Change a device's network role. Users given access by type gain or lose this device at once
    (resync_type_grants); nothing for FreeRADIUS to reload."""
    role = _checked_role(role)
    with transaction.atomic(using=DB):
        NasRole.objects.update_or_create(nasname=device.nasname, defaults={"role": role})
        resync_type_grants()
    return role


_RELOAD_CHECK = {"at": -1e9, "ok": True}


def reload_permission_ok():
    """True when the app may run RADIUS_RELOAD_CMD. For a sudo command this asks `sudo -n -l <command>`,
    which only checks the permission and does NOT restart anything. Cached for 5 minutes."""
    import time
    if time.monotonic() - _RELOAD_CHECK["at"] < 300:
        return _RELOAD_CHECK["ok"]
    cmd = shlex.split(settings.RADIUS_RELOAD_CMD)
    ok = True
    if cmd and cmd[0] == "sudo":
        rest = [c for c in cmd[1:] if c not in ("-n", "--non-interactive")]
        try:
            ok = subprocess.run(["sudo", "-n", "-l", *rest], capture_output=True, timeout=10).returncode == 0
        except Exception:
            ok = False
    _RELOAD_CHECK.update(at=time.monotonic(), ok=ok)
    return ok


def nas_added(nasname):
    """After a switch is added: with dynamic clients a single address works at once (no restart, so the
    switches never see FreeRADIUS go silent); otherwise, or for a network entry, restart FreeRADIUS.
    Returns (ok, restarted)."""
    if getattr(settings, "RADIUS_DYNAMIC_CLIENTS", False) and is_single_ip(nasname):
        return True, False
    return reload_radius(), True


def reload_radius():
    """FreeRADIUS reads the nas table only at start, so it is restarted after a device change."""
    try:
        r = subprocess.run(shlex.split(settings.RADIUS_RELOAD_CMD), capture_output=True, timeout=30)
        return r.returncode == 0
    except Exception:
        return False


def sync_firewall():
    """Keep UDP 1812/1813 open in ufw for exactly the devices on NAS Clients (RADIUS_FIREWALL_CMD, set by
    deploy/radius/enable_firewall_sync.sh; empty = off). The root script reads the addresses from the database
    itself and takes no arguments. It runs in the background so saving a device never waits for ufw.
    Returns True when a sync was started."""
    cmd = (getattr(settings, "RADIUS_FIREWALL_CMD", "") or "").strip()
    if not cmd:
        return False

    def run():
        with _FIREWALL_LOCK:
            try:
                r = subprocess.run(shlex.split(cmd), capture_output=True, text=True, timeout=180)
                if r.returncode:
                    logger.warning("RADIUS firewall sync failed (%s): %s", r.returncode, (r.stderr or r.stdout)[-300:])
            except Exception as exc:
                logger.warning("RADIUS firewall sync could not run: %s", exc)

    threading.Thread(target=run, name="radius-firewall-sync", daemon=True).start()
    return True


_FIREWALL_LOCK = threading.Lock()



def update_nas_type(device, vendor):
    """Change a device's type; FreeRADIUS reads nas.type on every login, so no restart is needed."""
    Nas.objects.filter(pk=device.pk).update(type=vendor)


def delete_nas(device):
    """Remove a device and restart FreeRADIUS so its access stops at once. Returns True when the restart worked."""
    nasname = device.nasname
    with transaction.atomic(using=DB):
        device.delete()
        NasRole.objects.filter(nasname=nasname).delete()
        resync_type_grants()
    sync_firewall()                     # close RADIUS in the firewall for this address
    return reload_radius()

# ---------- add one or many NAS clients at once ----------
MAX_NAS_BATCH = 200


def split_list(text):
    """"10.0.0.1, 10.0.0.2" (commas, semicolons or new lines) -> ["10.0.0.1", "10.0.0.2"]."""
    import re
    return [part.strip() for part in re.split(r"[,;\n]+", text or "") if part.strip()]


def add_nas_devices(addresses_text, names_text, vendor, secret="", description="", role=""):
    """Add one or several NAS clients. Addresses and names are comma-separated lists in the same order;
    with no names the addresses are used as names. Every entry is checked first: one invalid address or name
    saves nothing. Addresses already in NAS Clients (or listed twice) are skipped, not changed.
    All devices of one batch share one secret, vendor and network role (free text; empty = "Other").
    FreeRADIUS is restarted at most once, and only when needed (a network entry, or dynamic clients turned off).
    Returns {"added": [...], "skipped": [...], "secret", "reloaded", "restarted"}."""
    import ipaddress
    from apps.core.api import ApiError
    if vendor not in {key for key, _ in VENDORS}:
        raise ApiError(400, "Choose a valid vendor")
    role = _checked_role(role)
    addresses, names = split_list(addresses_text), split_list(names_text)
    if not addresses:
        raise ApiError(400, "Enter the device IP address, or several separated by commas")
    if len(addresses) > MAX_NAS_BATCH:
        raise ApiError(400, f"Add at most {MAX_NAS_BATCH} devices at once")
    if names and len(names) != len(addresses):
        raise ApiError(400, f"You entered {len(addresses)} address{'es' if len(addresses) != 1 else ''} and "
                            f"{len(names)} name{'s' if len(names) != 1 else ''}. Give one name per address, in the "
                            "same order, or leave Name empty to use the addresses as names.")
    names = names or [a[:32] for a in addresses]
    for addr, name in zip(addresses, names):
        if len(addr) > 128:
            raise ApiError(400, f"Address is too long: {addr[:40]}...")
        try:
            ipaddress.ip_network(addr, strict=False)
        except ValueError:
            raise ApiError(400, f"Not a valid device IP or network: {addr}")
        if len(name) > 32:
            raise ApiError(400, f"Name can be at most 32 characters: {name}")
    if secret and len(secret) < 12:
        raise ApiError(400, "Shared secret needs at least 12 characters (leave it empty to generate a strong one)")
    if len(secret) > 60 or len(description) > 200:
        raise ApiError(400, "Shared secret or description is too long")
    secret = secret or generate_secret()

    added, skipped, seen = [], [], set()
    with transaction.atomic(using=DB):
        for addr, name in zip(addresses, names):
            if addr in seen:
                skipped.append({"nasname": addr, "name": name, "reason": "listed twice"})
                continue
            seen.add(addr)
            if selectors.nas_exists(addr):
                skipped.append({"nasname": addr, "name": name, "reason": "already in NAS Clients (left unchanged)"})
                continue
            device = create_nas(addr, name, vendor, secret, description)
            added.append({"id": device.pk, "name": name, "nasname": addr})
        if added:
            set_nas_roles([d["nasname"] for d in added], role)
            resync_type_grants()        # users allowed on this type can log in on the new devices at once

    dynamic = getattr(settings, "RADIUS_DYNAMIC_CLIENTS", False)
    needs_restart = bool(added) and (not dynamic or any(not is_single_ip(d["nasname"]) for d in added))
    reloaded = reload_radius() if needs_restart else True
    if added:
        sync_firewall()                 # open RADIUS in the firewall for the new addresses
    return {"added": added, "skipped": skipped, "secret": secret if added else "",
            "reloaded": reloaded, "restarted": needs_restart}