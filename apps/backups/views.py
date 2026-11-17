"""Backups - HTTP layer: /api/backup, /api/jobs, /api/logs, /api/backups, /api/diff and the reports.

Views read the request, call selectors (reads) or services (changes), record the audit entry and answer.
Database queries, file handling and rules live in selectors.py, services.py, storage.py and reports.py.
"""
import csv
import logging

from django.http import FileResponse, HttpResponse, JsonResponse
from django.utils import timezone

from apps.core.api import ApiError, api
from apps.core.utils import csv_safe, fmt_dt, fmt_dt_ampm, parse_json

from . import audit, selectors, services
from .audit import record_audit


def _limit(request, default, maximum):
    try:
        return min(max(int(request.GET.get("limit", str(default))), 1), maximum)
    except ValueError:
        raise ApiError(400, "limit must be a number")


# ---------- jobs ----------
@api(POST="operator")
def start_backup(request):
    """Start a backup of the selected devices (all devices when none are selected)."""
    payload = parse_json(request)
    force_ssh = payload.get("force_ssh") is True
    job_id, count = services.start_manual_backup(payload.get("ids") or [], force_ssh, request.user.username)
    record_audit(request, "backup.manual_force_start" if force_ssh else "backup.manual_start",
                 f"{count} device(s)", f"job_id={job_id}; force_ssh={force_ssh}")
    return JsonResponse({"job": job_id})


@api(GET="viewer")
def job_active(request):
    """The backup that is running right now (started by anyone, or by the schedule); job is null when idle."""
    return JsonResponse(selectors.running_job())


@api(POST="operator")
def job_cancel(request):
    """Stop the running backup: devices that have not started are skipped."""
    job_id = services.stop_backup()
    record_audit(request, "backup.stop", f"job {job_id}", "Stop requested from the Devices page")
    return JsonResponse({"job": job_id})


@api(GET="viewer")
def job_status(request, job_id):
    """Progress of a backup job; the results are sent once it has finished."""
    return JsonResponse(selectors.job_progress(job_id))


@api(GET="viewer")
def jobs_history(request):
    """Backup Jobs page: the latest runs (up to ?limit=, max 200) with totals, duration and problem devices."""
    return JsonResponse(selectors.job_history(_limit(request, 200, 200)))


# ---------- activity log ----------
def _filtered_logs(request):
    """?status=, ?period=24H|7D|30D|90D|ALL, ?q= -> filtered log lines (see selectors.filtered_logs)."""
    return selectors.filtered_logs(request.GET.get("status"), request.GET.get("period"), request.GET.get("q"))


@api(GET="viewer")
def logs(request):
    """Log lines, newest first: up to ?limit= (default 1000, max 5000)."""
    return JsonResponse(selectors.log_rows(_filtered_logs(request), _limit(request, 1000, 5000)), safe=False)


@api(GET="viewer")
def logs_summary(request):
    """Counts for the Activity Logs tiles."""
    return JsonResponse(selectors.log_summary(_filtered_logs(request)))


@api(GET="admin")
def audit_events(request):
    """Admin-only audit trail. Secrets and raw configurations are never recorded here."""
    rows = audit.recent_events(_limit(request, 200, 1000))
    return JsonResponse([{"id": r.id, "ts": fmt_dt(r.ts), "username": r.username,
                          "action": r.action, "target": r.target, "detail": r.detail,
                          "remote_addr": r.remote_addr} for r in rows], safe=False)


@api(GET="viewer")
def alerts(request):
    """Current backup warnings derived from recent logs and the persisted recovery queue."""
    return JsonResponse(selectors.alerts())


@api(GET="viewer")
def notifications(request):
    """Top-bar notifications centre: a short list of problems that need attention, grouped by kind with a
    count each. Backup / device problems for everyone; RADIUS problems for administrators."""
    items = selectors.notifications()
    if request.user.has_role("admin"):
        try:
            from apps.radius import selectors as radius
            violations = radius.limit_violations()
        except Exception:
            violations = []
        if violations:
            users = sorted({v["username"] for v in violations})
            items.append({"key": "radius-limit", "severity": "warning", "icon": "shield", "count": len(users),
                          "title": f"Device limits not enforced for {len(users)} RADIUS user{'s' if len(users) != 1 else ''}",
                          "detail": ", ".join(users[:5]) + (f" and {len(users) - 5} more" if len(users) > 5 else ""),
                          "page": "radius-audit"})
    rank = {"critical": 0, "warning": 1, "info": 2}
    items.sort(key=lambda i: rank.get(i["severity"], 3))
    return JsonResponse({"items": items})


# ---------- saved versions ----------
@api(GET="viewer")
def backups(request):
    """One summary per device: version count and latest file, linked to a configured device."""
    return JsonResponse(selectors.backup_overview(), safe=False)


@api(GET="operator", DELETE="admin")
def device_backups(request, device):
    """GET: versions of a backup folder / device ([] for a device without backups). DELETE: remove them all."""
    if request.method == "DELETE":
        name, count = services.delete_device_backups(device)
        record_audit(request, "backup.delete_device", name, f"files={count}")
        return JsonResponse({"ok": True})
    return JsonResponse(selectors.folder_versions(device), safe=False)


@api(GET="operator")
def device_backup_tree(request, device_id):
    """The year/month/day backup folder tree of a configured device."""
    return JsonResponse(selectors.device_tree(device_id))


@api(GET="operator", DELETE="admin")
def backup_file(request, device, filename):
    """GET: show a backup as text (or download it with ?download=1). DELETE: remove that version."""
    if request.method == "DELETE":
        services.delete_version(device, filename)
        record_audit(request, "backup.delete_file", f"{device}/{filename}", "Backup version deleted")
        return JsonResponse({"ok": True})
    if request.GET.get("download"):
        path = selectors.version_path(device, filename)
        record_audit(request, "backup.download", f"{device}/{filename}")
        return FileResponse(open(path, "rb"), as_attachment=True, filename=path.name)
    # Viewing is a read: log it to the application log instead of writing a database row,
    # so opening a file never waits behind a running backup job's database writes.
    logging.getLogger("dbms").info("backup viewed by %s: %s/%s", getattr(request.user, "username", "?"), device, filename)
    return HttpResponse(selectors.version_text(device, filename), content_type="text/plain; charset=utf-8")


@api(GET="operator")
def diff(request, device):
    """Line-by-line comparison of two version paths supplied as ?a= and ?b=."""
    text = selectors.version_diff(device, request.GET.get("a", ""), request.GET.get("b", ""))
    return HttpResponse(text, content_type="text/plain; charset=utf-8")


@api(POST="admin")
def delete_all_backups(request):
    """Delete every backup of every device."""
    deleted = services.delete_all_backups()
    record_audit(request, "backup.delete_all", "all devices", f"files={deleted}")
    return JsonResponse({"deleted": deleted})


@api(POST="admin")
def delete_selected(request):
    """Delete every saved version of the chosen devices."""
    folders, deleted = services.delete_selected_backups(parse_json(request).get("names") or [])
    record_audit(request, "backup.delete_selected", f"{folders} device(s)", f"files={deleted}")
    return JsonResponse({"deleted": deleted})


@api(POST="operator")
def download_selected(request):
    """Zip of the chosen devices' backups: newest file of each, or every version when {"all": true}."""
    data = parse_json(request)
    every, names = bool(data.get("all")), data.get("names") or []
    buf, count = selectors.zip_selected(names, every)
    record_audit(request, "backup.download_zip", f"{len(names)} device(s)", f"files={count}; all_versions={every}")
    filename = "Selected_All_Backups.zip" if every else "Selected_Latest_Backups.zip"
    return FileResponse(buf, as_attachment=True, filename=filename, content_type="application/zip")


@api(GET="operator")
def download_all(request):
    """Zip with the newest backup of every device."""
    buf, count = selectors.zip_all_latest()
    record_audit(request, "backup.download_all", "all devices", f"files={count}")
    return FileResponse(buf, as_attachment=True, filename="All_Latest_Backups.zip", content_type="application/zip")


# ---------- reports ----------
@api(GET="viewer")
def change_report(request):
    """What changed on every device in the last ?months=1|3|6|12, or ?from=YYYY-MM&to=YYYY-MM (see reports.py)."""
    from .reports import PERIODS, change_report as report, month_range

    def build(*args, **kwargs):
        """Viewers may not read configurations (the Backups screen needs Operator), so they get the counts
        only: the changed configuration lines can hold password hashes and SNMP communities."""
        data = report(*args, **kwargs)
        if not request.user.has_role("operator"):
            data["preview_hidden"] = True
            for row in data["devices"]:
                for change in row["timeline"]:
                    change["preview"] = []
        return data
    if request.GET.get("from") or request.GET.get("to"):
        try:
            start, end = month_range(request.GET.get("from", ""), request.GET.get("to", ""))
        except ValueError as exc:
            raise ApiError(400, "Choose a valid month range: the start month must not be after the end month"
                           if "before" in str(exc) else "Choose both a start month and an end month")
        if start > timezone.localtime():
            raise ApiError(400, "The start month is in the future; there are no backups to report yet")
        return JsonResponse(build(start=start, end=end))
    try:
        months = int(request.GET.get("months", "1"))
    except ValueError:
        months = 0
    if months not in PERIODS:
        raise ApiError(400, "Choose a period of 1, 3, 6 or 12 months")
    return JsonResponse(build(months))


@api(GET="viewer")
def compliance_report(request):
    """CSV report of current inventory and latest backup outcome; contains no credentials/config."""
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="device_backup_compliance_{timezone.localtime():%Y%m%d_%H%M}.csv"'
    response.write("﻿")
    writer = csv.writer(response)
    writer.writerow(["Device ID", "Hostname", "IP", "Vendor/Type", "Last Status", "Last Backup Time", "Latest Log Message"])
    for device, log in selectors.compliance_rows():
        writer.writerow([csv_safe(v) for v in (device.pk, device.name, device.ip, device.device_type, device.last_status,
                                               fmt_dt_ampm(device.last_run),
                                               log.message[:500] if log else "No backup recorded")])
    record_audit(request, "report.compliance_export", "device inventory", "CSV compliance report exported")
    return response
