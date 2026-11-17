"""Devices - HTTP layer: the /api/devices and /api/credentials endpoints.

Views only read the request, call selectors (reads) or services (changes), record the audit entry and
answer. Rules and database access live in services.py and selectors.py.
"""
import csv

from django.conf import settings
from django.http import HttpResponse, JsonResponse

from apps.backups.audit import record_audit
from apps.core.api import ApiError, api
from apps.core.utils import csv_safe, fmt_dt_ampm, parse_json

from . import selectors, services


def _label(device):
    return f"{device.name or device.ip} ({device.ip})"


@api(GET="viewer", POST="operator")
def devices(request):
    """GET: all devices in IP order. POST: add one device and take its first backup."""
    if request.method == "GET":
        return JsonResponse([d.to_public() for d in selectors.devices_by_ip()], safe=False)
    data = parse_json(request)
    device = services.create_device(services.clean_payload(data), data.get("credential_id"), created_by=request.user)
    job, state = services.queue_initial_backup([device], request.user.username)
    record_audit(request, "device.add", _label(device), "Device created; initial backup queued")
    return JsonResponse({"ok": True, "initial_backup": state, "job": job})


@api(PUT="operator", DELETE="admin")
def device_detail(request, pk):
    """PUT: update one device (empty password keeps the saved one). DELETE: remove it (backup files stay)."""
    if request.method == "DELETE":
        device = selectors.get_device(pk)
        record_audit(request, "device.delete", _label(device), "Device removed; backup files were retained")
        services.delete_device(pk)
        return JsonResponse({"ok": True})
    data = parse_json(request)
    device = services.update_device(pk, services.clean_payload(data), data.get("credential_id"))
    record_audit(request, "device.update", _label(device), "Device inventory/settings updated")
    return JsonResponse({"ok": True})


@api(POST="admin")
def bulk_delete(request):
    """Delete the given device ids; an empty list deletes every device. Backup files stay on disk."""
    ids = parse_json(request).get("ids") or []
    deleted = services.delete_devices(ids)
    record_audit(request, "device.bulk_delete", "device inventory", f"deleted={deleted}; all={not ids}")
    return JsonResponse({"deleted": deleted})


@api(POST="operator")
def import_devices(request):
    """Paste one IP per line (optionally 'ip name') and apply shared settings."""
    data = parse_json(request)
    if not data.get("device_type"):
        raise ApiError(400, "Device type is required")
    detail = []
    created, skipped = services.import_devices(services.clean_payload(data), data.get("lines", ""),
                                               data.get("credential_id"), created_by=request.user,
                                               skipped_detail=detail)
    job, state = services.queue_initial_backup(created, request.user.username)
    for device in created:
        record_audit(request, "device.add", _label(device), "Device created by bulk import; initial backup queued")
    record_audit(request, "device.bulk_import", "device inventory",
                 f"added={len(created)}; skipped={skipped}; initial_backup={state}")
    return JsonResponse({"added": len(created), "skipped": skipped, "skipped_detail": detail[:50],
                         "added_ips": [d.ip for d in created][:50], "initial_backup": state, "job": job})


@api(GET="viewer")
def export_inventory(request):
    """Download a safe inventory CSV. Secret fields are deliberately never exported."""
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="dbms-device-inventory.csv"'
    response.write("﻿")  # Excel-friendly UTF-8 BOM
    writer = csv.writer(response)
    writer.writerow(["Name", "IP / Hostname", "Vendor / Type", "SSH Port", "Username",
                     "Backup Status", "Last Backup", "Custom Command"])
    for d in selectors.devices_by_id():
        writer.writerow([csv_safe(v) for v in (d.name, d.ip, d.device_type, d.port, d.username,
                                               d.last_status, fmt_dt_ampm(d.last_run), d.command)])
    return response


@api(GET="operator")
def credentials(request):
    """List saved credential profile metadata (passwords are not included)."""
    response = JsonResponse(selectors.credential_groups(), safe=False)
    response["Cache-Control"] = "no-store, private"
    return response


@api(POST="admin")
def credential_password(request):
    """Reveal one saved password only to an authenticated administrator after CSRF-protected selection."""
    if not settings.REVEAL_SAVED_PASSWORDS:
        raise ApiError(403, "Revealing saved passwords is turned off on this server")
    source, password = services.reveal_saved_password(parse_json(request).get("credential_id"))
    record_audit(request, "credential.reveal", f"profile {source.pk}",
                 "Saved password revealed to an authenticated administrator after explicit selection")
    response = JsonResponse({"password": password})
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    return response


@api(POST="operator")
def apply_credentials(request):
    """Set one username and password on several devices at once."""
    data = parse_json(request)
    ids = [i for i in (data.get("ids") or []) if isinstance(i, int)]
    updated, username = services.apply_credentials(ids, (data.get("username") or "").strip(),
                                                   data.get("password") or "", data.get("credential_id"))
    record_audit(request, "credentials.apply", f"{updated} device(s)", f"username={username}")
    return JsonResponse({"updated": updated})
