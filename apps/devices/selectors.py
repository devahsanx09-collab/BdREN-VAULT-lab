"""Devices - read layer: every database read of the device inventory.

Selectors only read; they never change data. Views and services call them; they call only models.
"""
from apps.core.api import ApiError

from .models import Device


def ip_sort_key(device):
    """10.1.0.2 sorts before 10.1.0.10 (numeric order, not text order)."""
    parts = device.ip.split(".")
    return (0, [int(x) for x in parts]) if len(parts) == 4 and all(x.isdigit() for x in parts) else (1, device.ip)


def devices_by_ip():
    """Every device, in IP order (the Device Inventory table)."""
    return sorted(Device.objects.all(), key=ip_sort_key)


def devices_by_id():
    """Every device in the order they were added (exports)."""
    return Device.objects.all().order_by("id")


def devices_with_ids(ids):
    """The devices with these ids; an empty list means every device."""
    return list(Device.objects.filter(id__in=ids) if ids else Device.objects.all())


def get_device(pk):
    """One device, or a 404 answer when it does not exist."""
    device = Device.objects.filter(pk=pk).first()
    if not device:
        raise ApiError(404, "Device not found")
    return device


def ip_in_use(ip, exclude_pk=None):
    """True when another device already has this IP address or hostname."""
    rows = Device.objects.filter(ip=ip)
    if exclude_pk is not None:
        rows = rows.exclude(pk=exclude_pk)
    return rows.exists()


def existing_ips():
    return set(Device.objects.values_list("ip", flat=True))


def saved_credential(credential_id, *, missing_status=400):
    """The device whose saved login is reused as a "saved credential" (password stays encrypted)."""
    try:
        source = Device.objects.get(pk=int(credential_id))
    except (TypeError, ValueError, Device.DoesNotExist):
        raise ApiError(missing_status, "Saved credential was not found" if missing_status == 404
                       else "Selected saved credential is no longer available")
    if not source.username or not source.password:
        raise ApiError(400, "Selected saved credential is incomplete")
    return source


def credential_groups():
    """Saved login profiles (username + which devices use it); passwords never leave the server."""
    groups = {}
    for d in Device.objects.exclude(password="").exclude(username="").order_by("-id"):
        try:
            # Decrypt only inside the server to group identical login profiles; never serialize it.
            key = (d.username, d.get_password())
        except Exception:
            continue
        g = groups.setdefault(key, {"credential_id": d.id, "username": d.username,
                                    "count": 0, "ids": [], "devices": []})
        g["count"] += 1
        g["ids"].append(d.id)
        g["devices"].append({"name": d.name, "ip": d.ip})
    return sorted(groups.values(), key=lambda g: (-g["count"], g["username"].lower(), g["credential_id"]))


def device_names(pk_list):
    """[{id, name, ip, last_status, last_run}] for these ids (alerts)."""
    return list(Device.objects.filter(pk__in=pk_list).values("id", "name", "ip", "last_status", "last_run"))


def failing_devices():
    """Devices whose latest backup attempt FAILED (current state), newest first - for the notifications centre."""
    return list(Device.objects.filter(last_status="FAILED").order_by("-last_run")
                .values("id", "name", "ip", "last_status", "last_run"))


def find_by_name_or_ip(value):
    """True when a device has this name or IP (case-insensitive)."""
    return Device.objects.filter(name__iexact=value).exists() or Device.objects.filter(ip__iexact=value).exists()


def id_ip_pairs(ids=None):
    """[(id, ip)] of these devices (all when ids is empty) - what the ping monitor needs."""
    rows = Device.objects.only("id", "ip")
    if ids:
        rows = rows.filter(id__in=ids)
    return [(d.id, d.ip) for d in rows]


def type_and_status():
    """[(device_type, last_status)] of every device - the Dashboard vendor and result charts."""
    return list(Device.objects.values_list("device_type", "last_status"))

def names_by_ip():
    """{ip: name} of every named device (to label RADIUS logins)."""
    return {ip: name for ip, name in Device.objects.values_list("ip", "name") if name}


def devices_with_pks(pks):
    """These devices, in the order they were added."""
    return list(Device.objects.filter(pk__in=pks).order_by("id"))


def devices_with_ips(ips):
    """The devices with these IP addresses, in the order they were added."""
    return list(Device.objects.filter(ip__in=ips).order_by("id"))
