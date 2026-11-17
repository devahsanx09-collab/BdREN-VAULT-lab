"""Settings page and the automatic-backup timer."""
import json
import re
import time
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from apps.core.api import ApiError
from apps.core.utils import DT_FORMAT

from .models import AppSetting

DEFAULTS = {"workers": None, "sched_on": "0", "sched_mode": "semimonthly", "sched_every": "60",
            "sched_at": "02:00", "sched_days": "1,15", "sched_catchup": "1", "sched_last": "0",
            "log_retention_months": "0"}
# Internal runtime keys must have defaults too. They are stored in AppSetting but are
# intentionally not exposed as editable form fields.
RUNTIME_DEFAULTS = {
    "pending_backup_device_ids": "[]",
    "pending_backup_ips": "[]",
    "pending_retry_after": "0",
    "queued_backup_device_ids": "[]",
    "initial_backup_pending": "0",
    "backup_job_heartbeat": "",
    "backup_job_cancel": "",
}
LOG_RETENTION_CHOICES = ("0", "1", "3", "6", "12", "24")   # months; "0" = keep logs forever
MODES = ("interval", "daily", "days", "semimonthly")          # every N minutes / every day at HH:MM / every N days


def get_setting(key):
    """Value of one setting from the database, or its default."""
    row = AppSetting.objects.filter(key=key).first()
    if row:
        return row.value
    if key == "workers":
        return str(settings.WORKERS)
    if key in DEFAULTS:
        return str(DEFAULTS[key])
    # Unknown/missing internal settings should never crash the scheduler or import API.
    return RUNTIME_DEFAULTS.get(key, "")


def get_json_list(key):
    """A list kept as JSON in one setting; missing or damaged data gives []."""
    try:
        value = json.loads(get_setting(key) or "[]")
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def get_id_list(key):
    """Device ids kept as a JSON list in one setting."""
    return [int(v) for v in get_json_list(key) if str(v).isdigit()]


def set_pending_devices(ids):
    """Store the devices whose scheduled backup must be retried, and when to retry (empty = no retry)."""
    ids = sorted({int(i) for i in ids})
    put_settings({"pending_backup_device_ids": json.dumps(ids),
                  "pending_retry_after": str(time.time() + settings.RECONNECT_RETRY_SECONDS) if ids else "0"})


# ---------- retry queue (docs/BACKUP_RELIABILITY.md) ----------
# Membership: "pending_backup_device_ids" (a list of device ids). Per device, "retry_info" keeps why it waits
# and when it is tried next: {"<id>": {"kind", "n" (queued attempts), "since", "next", "msg"}}.
RETRY_INFO_KEY = "retry_info"
RETRY_BACKOFF = {"transient": (600, 1800, 7200),     # 10 min, 30 min, 2 h, then give up
                 "auth": (900,)}                       # once after 15 min: never a loop that could lock the account


def retry_info():
    try:
        value = json.loads(get_setting(RETRY_INFO_KEY) or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def update_retry_queue(results, intended=(), cancelled=False):
    """Apply one job's results to the retry queue. Returns the ids that now wait for a retry.

    success or a permanent failure -> leaves the queue (a person must fix a permanent one);
    offline -> waits for its ping (checked every RECONNECT_RETRY_SECONDS) for at most RETRY_MAX_DAYS;
    transient / auth -> retried after the back-off above, then dropped;
    devices the job never reached (crash, power cut) -> retried like offline ones, unless an operator stopped it."""
    now = time.time()
    pending = set(get_id_list("pending_backup_device_ids"))
    info = retry_info()
    attempted = set()
    for row in results if isinstance(results, list) else []:
        if not isinstance(row, dict) or not str(row.get("device_id", "")).isdigit():
            continue
        dev = int(row["device_id"])
        key, status = str(dev), row.get("status")
        attempted.add(dev)
        prev = info.get(key) or {}
        if status in ("SUCCESS", "UNCHANGED"):
            pending.discard(dev)
            info.pop(key, None)
            continue
        if status != "FAILED":                      # CANCELLED: an operator stopped it; leave its queue state as is
            continue
        kind = row.get("failure") or ("offline" if row.get("offline") is True else "permanent")
        msg = str(row.get("message", ""))[:200]
        if kind == "offline":
            since = prev.get("since", now) if prev.get("kind") == "offline" else now
            if now - since > settings.RETRY_MAX_DAYS * 86400:
                pending.discard(dev)
                info.pop(key, None)
                continue
            pending.add(dev)
            info[key] = {"kind": "offline", "n": int(prev.get("n", 0)), "since": since,
                         "next": now + settings.RECONNECT_RETRY_SECONDS, "msg": msg}
        elif kind in RETRY_BACKOFF:
            n = int(prev.get("n", 0)) + 1 if prev.get("kind") == kind else 1
            delays = RETRY_BACKOFF[kind]
            if n > len(delays):                     # tried enough: stays FAILED for a person to look at
                pending.discard(dev)
                info.pop(key, None)
                continue
            pending.add(dev)
            info[key] = {"kind": kind, "n": n, "since": prev.get("since", now) if prev else now,
                         "next": now + delays[n - 1], "msg": msg}
        else:                                       # permanent: needs a person, no automatic retry
            pending.discard(dev)
            info.pop(key, None)
    if not cancelled:
        for dev in {int(i) for i in intended if str(i).isdigit()} - attempted:
            prev = info.get(str(dev)) or {}
            pending.add(dev)
            info[str(dev)] = {"kind": prev.get("kind", "offline"), "n": int(prev.get("n", 0)),
                              "since": prev.get("since", now), "next": now,
                              "msg": "The backup job stopped before it reached this device."}
    info = {k: v for k, v in info.items() if int(k) in pending}
    put_settings({"pending_backup_device_ids": json.dumps(sorted(pending)), RETRY_INFO_KEY: json.dumps(info),
                  "pending_retry_after": str(now + settings.RECONNECT_RETRY_SECONDS) if pending else "0"})
    return pending


def put_settings(values):
    for key, value in values.items():
        AppSetting.objects.update_or_create(key=key, defaults={"value": value})


def all_settings():
    return {key: get_setting(key) for key in DEFAULTS}


def clean_settings(data):
    """Validate the Settings form and return it as text values ready to store (raises ApiError 400)."""
    out = {}
    try:
        workers = int(data.get("workers", get_setting("workers")))
    except (TypeError, ValueError):
        raise ApiError(400, "Parallel sessions must be a number")
    if not 1 <= workers <= settings.MAX_WORKERS:
        raise ApiError(400, f"Parallel sessions must be between 1 and {settings.MAX_WORKERS} "
                            "(start with 10 on an 8 GB RAM PC)")
    out["workers"] = str(workers)
    out["sched_on"] = "1" if str(data.get("sched_on", "0")) in ("1", "true", "True") else "0"
    out["sched_mode"] = data.get("sched_mode") if data.get("sched_mode") in MODES else "interval"
    try:
        every = int(data.get("sched_every", DEFAULTS["sched_every"]))
    except (TypeError, ValueError):
        raise ApiError(400, "Schedule interval must be a whole number")
    if out["sched_mode"] == "days":
        if not 1 <= every <= 3650:
            raise ApiError(400, "Schedule interval must be between 1 and 3650 days")
    elif not 5 <= every <= 10080:
        raise ApiError(400, "Schedule interval must be between 5 and 10080 minutes")
    out["sched_every"] = str(every)
    at = data.get("sched_at") or "02:00"
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", at):
        raise ApiError(400, "Daily time must look like 02:00")
    out["sched_at"] = at
    raw_days = str(data.get("sched_days", get_setting("sched_days"))).strip()
    try:
        days = sorted({int(x.strip()) for x in raw_days.split(",") if x.strip()})
    except ValueError:
        raise ApiError(400, "Backup days must be comma-separated numbers, e.g. 1,15")
    if not days or any(day < 1 or day > 31 for day in days):
        raise ApiError(400, "Choose one or more backup days from 1 to 31")
    out["sched_days"] = ",".join(map(str, days))
    out["sched_catchup"] = "1" if str(data.get("sched_catchup", "0")) in ("1", "true", "True", "on") else "0"
    months = str(data.get("log_retention_months", get_setting("log_retention_months")))
    if months not in LOG_RETENTION_CHOICES:
        raise ApiError(400, "Choose how long to keep logs: forever, 1, 3, 6, 12 or 24 months")
    out["log_retention_months"] = months
    return out


def save_settings(data):
    """Validate and store the Settings form. Turning the schedule on starts counting from now."""
    out = clean_settings(data)
    if out["sched_on"] == "1" and get_setting("sched_on") != "1" and out["sched_mode"] != "semimonthly":
        out["sched_last"] = str(time.time())            # interval/daily modes begin counting from now
    put_settings(out)


def _schedule_days(values):
    """Return the configured days of month; invalid stored values safely fall back to 1 and 15."""
    try:
        days = sorted({int(x.strip()) for x in str(values.get("sched_days", "1,15")).split(",") if x.strip()})
        return days if days and all(1 <= day <= 31 for day in days) else [1, 15]
    except (TypeError, ValueError):
        return [1, 15]


def is_due(values, now=None):
    """True when the schedule says a backup of every device should start now."""
    if values["sched_on"] != "1":
        return False
    now = now or datetime.now(timezone.get_current_timezone())
    last = float(values["sched_last"] or 0)
    mode = values["sched_mode"]
    last_day = datetime.fromtimestamp(last, now.tzinfo).date() if last > 0 else None
    if mode in ("semimonthly", "daily"):
        scheduled_days = _schedule_days(values) if mode == "semimonthly" else list(range(1, 32))
        due_today = (now.day in scheduled_days and now.strftime("%H:%M") >= values["sched_at"]
                     and last_day != now.date())
        if due_today:
            return True
        # Optional catch-up: if the service was down at the scheduled time,
        # run the missed backup after startup for up to 24 hours, but never
        # repeat an occurrence already recorded as run.
        if values.get("sched_catchup", "1") == "1":
            previous = now.date() - timedelta(days=1)
            if previous.day in scheduled_days:
                at = datetime.strptime(values["sched_at"], "%H:%M").time()
                occurrence = datetime.combine(previous, at, tzinfo=now.tzinfo)
                return (now >= occurrence and now - occurrence <= timedelta(hours=24)
                        and (last <= 0 or last < occurrence.timestamp()))
        return False
    seconds = int(values["sched_every"]) * (86400 if mode == "days" else 60)
    return now.timestamp() - last >= seconds


def next_scheduled_run(values, now=None):
    """Next run as 'YYYY-MM-DD HH:MM' in the project time zone, or '' when the schedule is off."""
    if values["sched_on"] != "1":
        return ""
    now = now or datetime.now(timezone.get_current_timezone())
    last = float(values["sched_last"] or 0)
    if values["sched_mode"] == "semimonthly":
        at = datetime.strptime(values["sched_at"], "%H:%M").time()
        candidates = []
        days = _schedule_days(values)
        for offset in range(0, 14):
            month_index = now.month - 1 + offset
            year = now.year + month_index // 12
            month = month_index % 12 + 1
            import calendar
            for day in days:
                if day > calendar.monthrange(year, month)[1]:
                    continue
                candidate = datetime(year, month, day, at.hour, at.minute, tzinfo=now.tzinfo)
                last_day = datetime.fromtimestamp(last, now.tzinfo).date() if last > 0 else None
                if candidate >= now and not (candidate.date() == last_day):
                    candidates.append(candidate)
        if not candidates:
            month_index = now.month + 1
            year = now.year + (month_index - 1) // 12
            month = (month_index - 1) % 12 + 1
            import calendar
            candidates = [datetime(year, month, day, at.hour, at.minute, tzinfo=now.tzinfo)
                          for day in days if day <= calendar.monthrange(year, month)[1]]
        return min(candidates).strftime("%Y-%m-%d %H:%M")
    if values["sched_mode"] == "daily":
        at = datetime.strptime(values["sched_at"], "%H:%M").time()
        candidate = datetime.combine(now.date(), at, tzinfo=now.tzinfo)
        last_day = datetime.fromtimestamp(last, now.tzinfo).date() if last > 0 else None
        if candidate <= now:
            candidate = now if last_day != now.date() else candidate + timedelta(days=1)
        return candidate.strftime("%Y-%m-%d %H:%M")
    seconds = int(values["sched_every"]) * (86400 if values["sched_mode"] == "days" else 60)
    due = max(now.timestamp(), last + seconds)
    return datetime.fromtimestamp(due, now.tzinfo).strftime("%Y-%m-%d %H:%M")


def last_run_text(values):
    last = float(values["sched_last"] or 0)
    return datetime.fromtimestamp(last, timezone.get_current_timezone()).strftime(DT_FORMAT) if last > 0 else ""


def scheduler_tick():
    """One check of the timer: start a backup of every device when the schedule says it is due."""
    # imported here because backups.jobs imports this module (avoids a circular import)
    from apps.backups.jobs import job_running, start_job
    from apps.backups.services import trim_log_table
    from apps.devices import selectors as devices

    trim_log_table(20000)                                # keep the log table from growing forever
    # Recover database state from a prior process crash before deciding what to run.
    from apps.backups.jobs import close_stale_jobs
    close_stale_jobs()
    values = all_settings()
    if job_running():
        return

    # Missed-run recovery: retry ONLY the devices whose scheduled backup failed.
    # Never re-run the entire device inventory for recovery. Device IDs remain stable
    # if an IP address is edited. Legacy pending IPs are accepted for existing installs.
    pending_ids = get_json_list("pending_backup_device_ids")
    pending_ips = get_json_list("pending_backup_ips")
    try:
        retry_after = float(get_setting("pending_retry_after") or 0)
    except (TypeError, ValueError):
        retry_after = 0
    if (pending_ids or pending_ips) and time.time() >= retry_after:
        from apps.monitoring.services import ping_many
        if pending_ids:
            candidates = devices.devices_with_pks(pending_ids)
            gone = {int(i) for i in pending_ids if str(i).isdigit()} - {int(d.pk) for d in candidates}
            if gone:                                    # deleted devices leave the queue
                info = {k: v for k, v in retry_info().items() if int(k) not in gone}
                put_settings({"pending_backup_device_ids": json.dumps(sorted({int(d.pk) for d in candidates})),
                              RETRY_INFO_KEY: json.dumps(info)})
        else:
            candidates = devices.devices_with_ips(pending_ips)
        # Only devices whose back-off has passed (offline ones: every RECONNECT_RETRY_SECONDS).
        info, now = retry_info(), time.time()
        candidates = [d for d in candidates if float((info.get(str(d.pk)) or {}).get("next", 0)) <= now]
        # Recheck only the due devices concurrently (default every 60 seconds).
        # Never open SSH until ICMP is successful; the backup job performs a fresh
        # preflight immediately before SSH to avoid racing a device power-off.
        ping_results = ping_many([device.ip for device in candidates], recheck=False) if candidates else []
        retry_devices = [device for device, result in zip(candidates, ping_results) if result.get("up")]
        if retry_devices:
            job_id = start_job(retry_devices, "retry-after-reconnect")
            if job_id:
                # A reachable device gets an immediate backup, before the next normal schedule.
                # Keep IDs pending until the job records success/failure.
                put_settings({"pending_retry_after": str(time.time() + settings.RECONNECT_RETRY_SECONDS)})
                return
        # Whether still offline or temporarily unable to start a job, do not ping
        # the same offline inventory on every 30-second scheduler tick.
        put_settings({"pending_retry_after": str(time.time() + settings.RECONNECT_RETRY_SECONDS)})

    # If failed devices are still offline, do not block newly added devices forever.
    # Run their first backup after all currently reachable failed devices had priority.
    queued_ids = get_json_list("queued_backup_device_ids")
    # Give pending failures their full retry window before releasing new-device jobs.
    if queued_ids and (not (pending_ids or pending_ips) or time.time() >= retry_after):
        queued_devices = devices.devices_with_pks(queued_ids)
        if queued_devices and start_job(queued_devices, reason="device-added-queue"):
            put_settings({"queued_backup_device_ids": "[]"})
            return
        if not queued_devices:
            put_settings({"queued_backup_device_ids": "[]"})

    # One-time initial rollout: after the operator explicitly enables it with the
    # configure_auto_backup management command, back up the current inventory once.
    # This is a read-only SSH collection job; it does not push configuration to devices.
    if get_setting("initial_backup_pending") == "1":
        all_devices = list(devices.devices_by_id())
        if not all_devices:
            put_settings({"initial_backup_pending": "0"})
        elif start_job(all_devices, reason="initial-rollout"):
            put_settings({"initial_backup_pending": "0", "sched_last": str(time.time())})
            return

    # One global schedule applies to every configured device.
    due_global = is_due(values)
    due_devices = list(devices.devices_by_id()) if due_global else []
    if due_devices and start_job(due_devices, "scheduled"):
        put_settings({"sched_last": str(time.time())})
