"""Backups - read layer: jobs, logs, saved versions on disk, reports and the numbers other apps show.

Selectors only read (database, or the backup files through storage.py); they never change anything.
"""
import difflib
import json
from datetime import datetime, time as dtime, timedelta

from django.conf import settings
from django.db.models import Count, Q
from django.utils import timezone

from apps.core.api import ApiError
from apps.core.utils import fmt_dt
from apps.devices import selectors as devices

from . import storage
from .jobs import active_job, job_phase, summarize
from .models import BackupJob, BackupLog

GOOD = ("SUCCESS", "UNCHANGED")
LOG_PERIODS = {"24H": 1, "7D": 7, "30D": 30, "90D": 90}
JOB_REASONS = {"manual": "Manual backup", "manual-force": "Manual backup (forced SSH)", "scheduled": "Scheduled backup",
               "device-added": "New device", "device-added-queue": "New device (queued)",
               "initial-rollout": "Initial rollout", "retry-after-reconnect": "Retry after reconnect"}


# ---------- jobs ----------
def running_job():
    """{job, total, done, reason} of the backup running now, or {job: None}."""
    job = active_job()
    if not job:
        return {"job": None}
    return {"job": job.pk, "total": job.total, "done": job.done, "reason": job.reason}


def job_progress(job_id):
    job = BackupJob.objects.filter(pk=job_id).first()
    if not job:
        raise ApiError(404, "Not found")
    return {"total": job.total, "done": job.done, "finished": job.finished,
            "phase": "" if job.finished else job_phase(job.pk),
            "results": job.results if job.finished else []}


RETRY_KIND_TEXT = {"offline": "Offline: waiting for the device to answer ping",
                   "transient": "Temporary problem (timeout, silent device or dropped session)",
                   "auth": "Login was rejected (a busy AAA server can do this): one more try"}


def retry_queue():
    """Devices that wait for an automatic retry: why, since when, how many tries, when the next check is."""
    from apps.scheduling.services import get_id_list, retry_info
    ids = get_id_list("pending_backup_device_ids")
    info = retry_info()
    tz = timezone.get_current_timezone()
    when = lambda ts: fmt_dt(datetime.fromtimestamp(float(ts), tz)) if ts else ""
    rows = []
    for d in devices.device_names(ids):
        i = info.get(str(d["id"])) or {}
        kind = i.get("kind", "offline")
        rows.append({"id": d["id"], "name": d["name"] or d["ip"], "ip": d["ip"], "kind": kind,
                     "why": RETRY_KIND_TEXT.get(kind, kind), "attempts": int(i.get("n", 0)),
                     "since": when(i.get("since")), "next": when(i.get("next")), "message": i.get("msg", "")})
    return sorted(rows, key=lambda r: (r["kind"] != "transient", r["name"].lower()))


def configured_workers():
    """Parallel SSH sessions set on the Settings page."""
    from apps.scheduling.services import get_setting
    try:
        return max(1, min(int(get_setting("workers")), settings.MAX_WORKERS))
    except (TypeError, ValueError):
        return settings.WORKERS


def job_history(limit=200):
    """Backup Jobs page: the latest runs with totals, duration and problem devices.
    Finished jobs are read from their stored summary; a running job is summarised from its live results."""
    out = []
    # full device results are only read for a running job (deferred fields load on first use)
    for job in BackupJob.objects.order_by("-created").defer("device_ids", "results")[:limit]:
        summ = job.summary if (job.finished and job.summary) else summarize(job.results)
        end = job.finished_at or (timezone.now() if not job.finished else None)
        out.append({
            "id": job.pk, "reason": job.reason, "reason_label": JOB_REASONS.get(job.reason, job.reason or "Backup"),
            "started_by": job.started_by or "System", "started": fmt_dt(job.created),
            "finished": job.finished, "finished_at": fmt_dt(job.finished_at) if job.finished_at else "",
            "duration_s": round((end - job.created).total_seconds()) if end else None,
            "total": job.total, "done": job.done, "counts": summ.get("counts", {}),
            "avg_device_s": summ.get("avg_device_s"), "problems": summ.get("problems", []),
            "failed_ids": summ.get("failed_ids", []),
        })
    return {"jobs": out, "workers": configured_workers(), "retry_queue": retry_queue()}


# ---------- activity log ----------
def filtered_logs(status="ALL", period="ALL", q=""):
    """Log lines filtered IN THE DATABASE, newest first. With 500-1000 devices one scheduled run alone writes
    1000 lines, so filtering only the newest rows in the browser would hide every older event."""
    rows = BackupLog.objects.all()
    status = (status or "ALL").upper()
    if status in ("SUCCESS", "UNCHANGED", "FAILED"):
        rows = rows.filter(status=status)
    period = (period or "ALL").upper()
    if period in LOG_PERIODS:
        rows = rows.filter(ts__gte=timezone.now() - timedelta(days=LOG_PERIODS[period]))
    q = (q or "").strip()[:100]
    if q:
        rows = rows.filter(Q(name__icontains=q) | Q(ip__icontains=q) | Q(message__icontains=q))
    return rows


def log_rows(rows, limit):
    return [{"id": r.id, "ts": fmt_dt(r.ts), "ip": r.ip, "name": r.name, "status": r.status, "message": r.message}
            for r in rows[:limit]]


def log_summary(rows):
    """Counts for the Activity Logs tiles: all matching events, today's, and per result (computed in SQL)."""
    by_status = dict(rows.values_list("status").annotate(n=Count("id")).values_list("status", "n"))
    start_today = timezone.make_aware(datetime.combine(timezone.localdate(), dtime.min), timezone.get_current_timezone())
    return {"total": sum(by_status.values()), "today": rows.filter(ts__gte=start_today).count(),
            "saved": by_status.get("SUCCESS", 0), "unchanged": by_status.get("UNCHANGED", 0),
            "failed": by_status.get("FAILED", 0)}


# ---------- saved versions (files on disk) ----------
def backup_overview():
    """One summary per device folder (version count, latest file), linked to a configured device;
    devices without any backup yet are listed too."""
    rows = storage.summaries()
    # Load the small lookup sets once (no query per folder).
    device_list = list(devices.devices_by_id().only("id", "ip", "name"))
    by_ip = {d.ip: d for d in device_list}
    by_name = {}
    for d in device_list:
        if d.name and d.name not in by_name:
            by_name[d.name] = d
    latest_log_ip = {}
    for item in BackupLog.objects.filter(status__in=GOOD).order_by("-id").values("name", "ip"):
        latest_log_ip.setdefault(item["name"], item["ip"])
    seen_ids = set()
    for row in rows:
        log_ip = latest_log_ip.get(row["name"])
        device_obj = by_ip.get(log_ip) if log_ip else by_name.get(row["name"])
        if not device_obj and row["name"].count("_") >= 3:
            device_obj = by_ip.get(row["name"].replace("_", "."))
        row["device_id"] = device_obj.id if device_obj else None
        if device_obj:
            seen_ids.add(device_obj.id)
    for device_obj in device_list:
        if device_obj.id in seen_ids:
            continue
        folder_name = storage.safe_name(device_obj.name or device_obj.ip.replace(".", "_"))
        rows.append({"name": folder_name, "count": 0,
                     "latest": {"file": "", "name": "", "size": 0, "time": "Never"},
                     "previous": "", "device_id": device_obj.id})
    return sorted(rows, key=lambda r: (r["count"] == 0, r["name"].lower()))


def folder_versions(device):
    """Saved versions of one backup folder, newest first. A configured device without files gives []."""
    try:
        folder = storage.folder_of(device)
    except ApiError as exc:
        if exc.status == 404 and devices.find_by_name_or_ip(device):
            return []
        raise
    return [storage.file_info(f, folder) for f in reversed(storage.versions(folder))]


def device_tree(device_id):
    """The year / month / day folder tree of one configured device."""
    device_obj = devices.get_device(device_id)
    latest_log = BackupLog.objects.filter(ip=device_obj.ip, status__in=GOOD).order_by("-id").first()
    candidates = [latest_log.name if latest_log and latest_log.name else "", device_obj.name, device_obj.ip.replace(".", "_")]
    folder = next((storage.device_folder(n) for n in candidates if n and storage.device_folder(n).is_dir()), None)
    if folder is None:
        return {"device": storage.safe_name(device_obj.name or device_obj.ip.replace(".", "_")), "years": []}
    return storage.tree_for_device(folder)


def version_path(device, filename):
    return storage.resolve(device, filename)


def version_text(device, filename):
    return storage.read_text(storage.resolve(device, filename))


def version_diff(device, a, b):
    """Unified diff of two versions of one device."""
    if not a or not b:
        raise ApiError(400, "Two backup versions are required")
    lines_a = version_text(device, a).splitlines()
    lines_b = version_text(device, b).splitlines()
    return "\n".join(difflib.unified_diff(lines_a, lines_b, a, b, lineterm="", n=2)) or "(no differences)"


def zip_selected(names, every_version):
    """(zip buffer, file count) of the chosen devices: newest file of each, or every version."""
    buf, count = storage.zip_of(storage.folders_of(names), every_version)
    if not count:
        raise ApiError(404, "No backup files found for the selected devices")
    return buf, count


def zip_all_latest():
    return storage.zip_of([f for f in storage.root().iterdir() if f.is_dir()])


# ---------- reports ----------
def compliance_rows():
    """(device, latest log line or None) for the compliance CSV, in inventory order."""
    return [(device, BackupLog.objects.filter(ip=device.ip).order_by("-id").first())
            for device in devices.devices_by_id()]


def _names_line(names, keep=5):
    """"A, B, C and 4 more" from a list of names, for a notification's one-line detail."""
    shown = ", ".join(names[:keep])
    extra = len(names) - keep
    return f"{shown} and {extra} more" if extra > 0 else shown


def notifications():
    """Problems to show in the top-bar notifications centre: devices whose last backup failed (and are not
    already waiting for an automatic retry), and the devices the self-healing retry queue is handling. Each
    item is a grouped card with a count, so a big inventory never floods the list. RADIUS problems are added
    in the view (admins only)."""
    queue = retry_queue()
    retry_ids = {r["id"] for r in queue}
    failing = [d for d in devices.failing_devices() if d["id"] not in retry_ids]
    items = []
    if failing:
        names = [d["name"] or d["ip"] for d in failing]
        items.append({"key": "backup-failed", "severity": "warning", "icon": "backup", "count": len(failing),
                      "title": f"{len(failing)} device{'s' if len(failing) != 1 else ''} failed the last backup",
                      "detail": _names_line(names), "page": "devices"})
    if queue:
        names = [r["name"] for r in queue]
        items.append({"key": "retry", "severity": "info", "icon": "retry", "count": len(queue),
                      "title": f"{len(queue)} device{'s' if len(queue) != 1 else ''} waiting to retry automatically",
                      "detail": _names_line(names), "page": "jobs"})
    return items


def alerts():
    """Current backup warnings from recent logs and the recovery queue."""
    from apps.scheduling.services import get_setting
    try:
        pending_ids = [int(x) for x in json.loads(get_setting("pending_backup_device_ids") or "[]")]
    except (TypeError, ValueError):
        pending_ids = []
    pending = devices.device_names(pending_ids)
    failed, seen = [], set()
    for row in BackupLog.objects.filter(status="FAILED").order_by("-id")[:1000]:
        if row.ip in seen:
            continue
        seen.add(row.ip)
        failed.append({"ip": row.ip, "name": row.name, "ts": fmt_dt(row.ts), "message": row.message})
    return {"pending_recovery_count": len(pending), "pending_recovery": pending, "retry_queue": retry_queue(),
            "latest_failed_devices": failed[:100],
            "disk_warning": "Use `python manage.py system_health` for disk-space and host checks."}


# ---------- numbers for the Dashboard (apps/monitoring) ----------
def results_per_day(days):
    """{"YYYY-MM-DD": {"ok", "same", "bad"}} for these local dates.
    Grouped in Python, not SQL: `ts__date` makes MySQL call CONVERT_TZ, which returns NULL unless the
    MySQL time-zone tables were loaded. Comparing plain datetimes works on every database."""
    per_day = {d.isoformat(): {"ok": 0, "same": 0, "bad": 0} for d in days}
    key_of = {"SUCCESS": "ok", "UNCHANGED": "same", "FAILED": "bad"}
    first_moment = timezone.make_aware(datetime.combine(days[0], dtime.min), timezone.get_current_timezone())
    for ts, status in BackupLog.objects.filter(ts__gte=first_moment).values_list("ts", "status").iterator(chunk_size=2000):
        key = key_of.get(status)
        day = timezone.localtime(ts).date().isoformat()
        if key and day in per_day:
            per_day[day][key] += 1
    return per_day


def last_good_backup_time():
    return BackupLog.objects.filter(status__in=GOOD).order_by("-ts").values_list("ts", flat=True).first()


def failed_since(hours):
    return BackupLog.objects.filter(status="FAILED", ts__gte=timezone.now() - timedelta(hours=hours)).count()
