"""Devices - business layer: validation and every change to the device inventory.

Services own the rules (unique IP, valid address, allowed command) and all writes. They call selectors for
reads and models to save. Views call services; services never touch the request.
"""
import re

from apps.core.api import ApiError
from apps.core.crypto import encrypt

from . import selectors
from .models import Device
from .vendors import ALIASES, HOSTRX, VENDORS

IPLIKE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


def _is_special_use(value):
    """True for literal loopback, link-local, multicast, unspecified or reserved IP addresses."""
    import ipaddress
    try:
        a = ipaddress.ip_address(value)
    except ValueError:
        return False          # a hostname: checked at connect time by core.netguard
    return a.is_loopback or a.is_link_local or a.is_multicast or a.is_unspecified or a.is_reserved


# ---------- validation ----------
def clean_payload(data):
    """Validate a device payload from the browser and return plain values.
    'password' / 'secret' are only present when the person typed one (an empty password keeps the old one)."""
    data = data or {}
    out = {k: data[k].strip() if isinstance(data.get(k), str) else ""
           for k in ("name", "ip", "device_type", "username", "command")}
    if out["ip"] and not HOSTRX.match(out["ip"]):
        raise ApiError(400, "IP address or hostname is not valid")
    if out["ip"] and _is_special_use(out["ip"]):
        raise ApiError(400, "This address is loopback or special-use and cannot be backed up")
    if out["command"]:
        from apps.backups.engine import command_problem
        if problem := command_problem(out["command"]):
            raise ApiError(400, f"Custom command {problem}")
    out["device_type"] = ALIASES.get(out["device_type"], out["device_type"])
    if out["device_type"] and out["device_type"] not in VENDORS:
        raise ApiError(400, "Unknown device type")
    if out["device_type"] == "other" and not out["command"]:
        raise ApiError(400, "Custom command is required for the Other device type")
    if len(out["name"]) > 100 or len(out["command"]) > 500:
        raise ApiError(400, "Name or command is too long")
    try:
        out["port"] = int(data.get("port") or 22)
    except (TypeError, ValueError):
        raise ApiError(400, "SSH port must be a number")
    if not 1 <= out["port"] <= 65535:
        raise ApiError(400, "SSH port must be between 1 and 65535")
    for key in ("password", "secret"):
        if data.get(key):
            out[key] = data[key]
    return out


def _require_basics(cleaned):
    if not cleaned["ip"] or not cleaned["device_type"]:
        raise ApiError(400, "IP and device type are required")


def apply_payload(device, cleaned):
    """Copy cleaned values onto a Device (encrypting passwords) without saving."""
    for field in ("name", "ip", "device_type", "username", "command", "port"):
        setattr(device, field, cleaned[field])
    if "password" in cleaned:
        device.set_password(cleaned["password"])
    if "secret" in cleaned:
        device.set_secret(cleaned["secret"])
    return device


def apply_saved_credential(device, credential_id):
    """Copy a saved encrypted credential server-side; the plaintext never reaches the browser."""
    if credential_id in (None, ""):
        return device
    source = selectors.saved_credential(credential_id)
    device.username = source.username
    device.password = source.password
    return device


# ---------- add / edit / delete ----------
def create_device(cleaned, credential_id=None, created_by=None):
    """Add one device (the IP must be unique). Returns the saved device."""
    _require_basics(cleaned)
    if selectors.ip_in_use(cleaned["ip"]):
        raise ApiError(409, "A device with this IP already exists")
    device = apply_payload(Device(), cleaned)
    if not cleaned.get("password"):
        apply_saved_credential(device, credential_id)
    device.created_by = created_by
    device.save()
    return device


def update_device(pk, cleaned, credential_id=None):
    """Change one device; an empty password keeps the saved one. Returns the saved device."""
    _require_basics(cleaned)
    if selectors.ip_in_use(cleaned["ip"], exclude_pk=pk):
        raise ApiError(409, "A device with this IP already exists")
    device = selectors.get_device(pk)
    apply_payload(device, cleaned)
    if not cleaned.get("password"):
        apply_saved_credential(device, credential_id)
    device.save()
    return device


def delete_device(pk):
    """Remove one device (its backup files stay on disk). Returns the removed device (for the audit text)."""
    device = selectors.get_device(pk)
    device.delete()
    return device


def delete_devices(ids):
    """Remove these devices; an empty list removes every device. Returns how many were removed."""
    rows = Device.objects.filter(id__in=ids) if ids else Device.objects.all()
    return rows.delete()[1].get("devices.Device", 0)


def parse_lines(text):
    """IPs separated by newline, comma, semicolon or space. A line with exactly 'ip name' sets the name."""
    out = []
    for line in text.splitlines():
        tokens = [x for x in re.split(r"[,;\s]+", line.strip()) if x]
        if len(tokens) == 2 and IPLIKE.match(tokens[0]) and not IPLIKE.match(tokens[1]):
            out.append((tokens[0], tokens[1]))
        else:
            out += [(x, "") for x in tokens]
    return out


def import_devices(base, lines, credential_id=None, created_by=None, skipped_detail=None):
    """Create one device per pasted line using shared settings. Returns (created_devices, skipped).
    When `skipped_detail` is a list, one {"ip", "reason"} entry is appended per skipped address."""
    created_devices = []
    skipped = 0
    existing = selectors.existing_ips()
    for ip, name in parse_lines(lines):
        reason = ("not a valid IP address or hostname" if not HOSTRX.match(ip) else
                  "already in the device list" if ip in existing else
                  "reserved / special-use address" if _is_special_use(ip) else "")
        if reason:
            skipped += 1
            if skipped_detail is not None:
                skipped_detail.append({"ip": ip[:64], "reason": reason})
            continue
        device = apply_payload(Device(), dict(base, ip=ip, name=name[:100]))
        if not base.get("password") and credential_id not in (None, ""):
            apply_saved_credential(device, credential_id)
        if created_by is not None:
            device.created_by = created_by
        device.save()
        existing.add(ip)
        created_devices.append(device)
    return created_devices, skipped


def queue_initial_backup(devices, started_by):
    """Back up newly added devices at once (or queue them behind a running job).
    Returns (job id or "queued" or None, "started" | "queued" | "not_needed")."""
    if not devices:
        return None, "not_needed"
    from apps.backups.jobs import start_job
    job = start_job(list(devices), reason="device-added", started_by=started_by)
    return job, "started" if job and job != "queued" else "queued"


# ---------- saved logins ----------
def reveal_saved_password(credential_id):
    """The plain password of a saved login (administrators only; the view audits it)."""
    source = selectors.saved_credential(credential_id, missing_status=404)
    try:
        password = source.get_password()
    except Exception:
        raise ApiError(500, "Saved credential could not be decrypted")
    if not password:
        raise ApiError(400, "Selected saved credential is empty")
    return source, password


def apply_credentials(ids, username, password, credential_id=None):
    """Set one username and password on several devices. Returns (updated count, username used)."""
    if not ids:
        raise ApiError(400, "Select at least one device")
    if credential_id not in (None, ""):
        source = selectors.saved_credential(credential_id)
        username, encrypted_password = source.username, source.password
    elif username and password:
        encrypted_password = encrypt(password)
    else:
        raise ApiError(400, "Select a saved credential or enter a username and password")
    updated = Device.objects.filter(id__in=ids).update(username=username, password=encrypted_password)
    return updated, username


def record_backup_status(device_pk, status, name=""):
    """Store a backup result on the device: last status and time, and the hostname read from the device.
    Called by apps.backups inside ITS transaction, so the log line, the file and this change are kept together."""
    from django.utils import timezone
    fields = {"last_status": status, "last_run": timezone.now()}
    if name:
        fields["name"] = name                        # keep the inventory name in step with the live hostname
    Device.objects.filter(pk=device_pk).update(**fields)
