"""Back up one device and save a snapshot only when the normalized config changes.

All-or-nothing rule: a backup changes the database and the backup folder ONLY when it completed.
  * Completed (saved or unchanged): the log line, the device status / name and the new configuration
    file are written together in ONE database transaction. The file is written to a hidden temporary
    name first and renamed into place inside that transaction, so either both exist or neither does.
  * Not completed (offline, login refused, SSH dropped, command rejected, database error ...): nothing
    is saved and the device's name and saved configurations stay exactly as they were. Only the failure
    itself is logged (a log line plus the FAILED status), so operators can see what went wrong.
  * Stopped by an operator, or abandoned after a hang: nothing at all is written for that device, even
    if its SSH session answers later.
"""
import logging
import re
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from . import engine, storage
from .models import BackupLog, Status

logger = logging.getLogger("dbms")

# Lines that change on every run although the configuration did not. They are ignored when deciding
# whether a configuration changed (so no duplicate backup is saved) and in the change report.
VOLATILE = re.compile(
    # comment lines ("!", "!!", "#", "##", ":") carrying save / commit times: IOS, IOS XR, NX-OS, Junos, ASA
    r"(?i)^\s*(?:[#!:]+\s*(?:last configuration|last commit|nvram config|written by|saved\b|\d{4}-\d{2}-\d{2}"
    r"|[a-z]{3}/\d{1,2}/\d{4}|time:)"
    # IOS XR (and some others) print the clock as the first line: "Thu Nov 12 11:26:40.286 UTC"
    r"|(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}"
    r"\s+\d{1,2}:\d{2}:\d{2}(?:\.\d+)?(?:\s+\d{4})?(?:\s+[a-z]{2,5}(?:[+-]\d{1,2}(?::?\d{2})?)?)?(?:\s+\d{4})?\s*$"
    r"|ntp clock-period|building configuration|current configuration\s*:|using \d+ out of \d+ bytes)")

NOTHING_SAVED = "Nothing was saved and the previous backup is still the latest."
STOPPED_MESSAGE = ("Stopped by an operator before this device finished. Nothing was saved and the device "
                   "record was not changed.")


class BackupStopped(Exception):
    """The job was stopped while this device was still running: discard everything."""


class SaveFailed(Exception):
    """The configuration was read but could not be stored; everything was rolled back."""


def normalize(text):
    return "\n".join(l.rstrip() for l in text.splitlines() if not VOLATILE.match(l))


def _stopped(abort):
    return abort is not None and abort.is_set()


def commit_result(device, name, status, message, *, staged=None, abort=None):
    """Record a COMPLETED backup in one transaction: log line + device status/name (+ publish the file).

    Raises when anything fails; then nothing of it is kept (database rolled back, file removed)."""
    from apps.devices import services as devices
    name = (name or "")[:100]              # BackupLog.name / Device.name are 100 chars; MySQL strict mode rejects more
    try:
        with transaction.atomic():
            if _stopped(abort):
                raise BackupStopped()
            BackupLog.objects.create(ip=device.ip, name=name, status=status, message=message)
            devices.record_backup_status(device.pk, status, name)
            if staged is not None:
                storage.publish_staged(staged)          # last step: a failed rename rolls the rows back
    except BaseException as exc:
        if staged is not None:
            storage.discard_staged(staged)              # also covers a commit that failed after the rename
        if isinstance(exc, (BackupStopped, SaveFailed)) or not isinstance(exc, Exception):
            raise
        # the technical reason goes to the server log only; the screen gets a plain, safe sentence
        logger.exception("Could not store the backup of %s", device.ip)
        what = "the backup folder could not be written" if isinstance(exc, OSError) else "the database did not accept the record"
        raise SaveFailed(f"The configuration was read from the device, but it could not be stored ({what}; "
                         f"details are in the server log). {NOTHING_SAVED}") from exc


def record_failure(device, label, message):
    """Log a backup that did NOT complete. Only the log line and the FAILED status are written:
    the device name and its saved configurations are left untouched. Never raises."""
    from apps.devices import services as devices
    try:
        with transaction.atomic():
            BackupLog.objects.create(ip=device.ip, name=(label or "")[:100], status=Status.FAILED, message=message)
            devices.record_backup_status(device.pk, Status.FAILED)
    except Exception:
        logger.exception("Could not write the failure log for %s", device.ip)


def finalize_failure(device, label, message, kind, reason=""):
    """Write a FINAL failure: the log line, the FAILED status and (optionally) the alert.
    A temporary failure alerts only when the background retry fails too."""
    record_failure(device, label, message)
    if kind != "transient" or reason == "retry-after-reconnect":
        try:
            from apps.core.alerts import notify_backup_failure
            notify_backup_failure(device, message)
        except Exception:
            pass


def _result(device, name, status, **extra):
    return {"device_id": device.pk, "ip": device.ip, "name": name, "status": status, **extra}


def _stopped_result(device, label):
    return _result(device, label, "CANCELLED", message=STOPPED_MESSAGE)


def backup_device(device, reason="", preflight=None, abort=None, defer_retryable=False):
    """Back up one device. `abort` (threading.Event) is set by the job when an operator presses Stop backup.

    Nothing reaches the database before the outcome is final: a complete backup is saved in one transaction,
    and a failure is written once it is final. With `defer_retryable` (the job's first pass) a temporary or
    login failure is NOT written: the row carries "deferred": True and the job writes it only if the second
    try fails as well (finalize_failure)."""
    label = device.name or device.ip
    suffix = f" ({reason})" if reason else ""
    try:
        from apps.core.netguard import resolve_allowed_host
        # Batch jobs pass a completed preflight result so every device is pinged before
        # the SSH phase begins. Single-device calls can still perform their own check.
        approved_ip = (preflight.get("approved_ip") if preflight is not None
                       else resolve_allowed_host(device.ip))
        if not approved_ip:
            message = ("The device address could not be resolved, or it is a reserved address that backups may "
                       "not connect to. Check the IP address or hostname. " + NOTHING_SAVED)
            record_failure(device, label, message)
            return _result(device, label, Status.FAILED, message=message, offline=False, failure="permanent")

        # Normal automatic/manual backup: ICMP pre-check prevents pointless SSH attempts
        # to powered-off devices. Explicit manual Force SSH bypasses only this pre-check.
        if reason != "manual-force":
            if preflight is not None:
                reachability = preflight.get("ping") or {"up": False, "ms": None}
            else:
                from apps.monitoring.services import ping_host
                reachability = ping_host(approved_ip)
            if not reachability.get("up"):
                message = ("Device is offline: it did not answer ping, so no SSH login was attempted. "
                           + NOTHING_SAVED + " It waits in the retry queue and is backed up as soon as it answers.")
                record_failure(device, label, message)
                return _result(device, label, Status.FAILED, message=message, offline=True, failure="offline")

        if _stopped(abort):
            return _stopped_result(device, label)
        fetched = engine.fetch_config(device, approved_ip=approved_ip)
        if _stopped(abort):                  # the session answered after Stop backup: discard what it read
            return _stopped_result(device, label)

        name = fetched.hostname or device.name or fetched.prompt or device.ip.replace(".", "_")
        now = timezone.localtime()
        last = storage.latest_file(storage.device_folder(name))
        if last and normalize(storage.read_text(last)) == normalize(fetched.text):
            last_dt = datetime.fromtimestamp(last.stat().st_mtime, tz=timezone.get_current_timezone())
            changed = last_dt.strftime("%Y-%m-%d %H:%M:%S")
            message = (f"No configuration change since {changed}; the saved version {last.name} is kept "
                       f"as the latest{suffix}")
            commit_result(device, name, Status.UNCHANGED, message, abort=abort)
            try:                             # day metadata for the Backups tree; the database is already correct
                meta = storage.record_unchanged(name, now, last, changed)
            except Exception:
                logger.exception("Could not write run.json for %s", name)
                meta = {"last_change_date": changed}
            return _result(device, name, Status.UNCHANGED, last_change_date=meta.get("last_change_date") or changed)

        staged = storage.stage_backup(name, fetched.text, now)
        commit_result(device, name, Status.SUCCESS,
                      f"Configuration changed; new version saved as {staged.rel}{suffix}", staged=staged, abort=abort)
        try:                                 # checksum + run.json + pruning; the backup itself is already safe
            storage.finalize_backup(staged)
        except Exception:
            logger.exception("Saved %s but could not write its checksum / day metadata", staged.rel)
        return _result(device, name, Status.SUCCESS, file=staged.rel)
    except BackupStopped:
        return _stopped_result(device, label)
    except SaveFailed as exc:
        message, kind = str(exc), "transient"
    except Exception as exc:
        message, kind = engine.explain_failure(exc, device), engine.failure_kind(exc)
    if defer_retryable and kind in ("transient", "auth"):
        # Not final yet: the job tries this device again; nothing is written to the database now.
        return _result(device, label, Status.FAILED, message=message, failure=kind, deferred=True)
    # Notifications are optional and independently guarded; an alert outage must not
    # change the backup result or stop the remaining devices in a batch.
    finalize_failure(device, label, message, kind, reason)
    return _result(device, label, Status.FAILED, message=message, failure=kind)


# ---------- operator actions (called by views.py) ----------
# jobs.py imports this module, so the job runner is imported inside the functions (no import cycle).
def start_manual_backup(ids, force_ssh, started_by):
    """Start a backup of the selected devices (all when none are selected). Returns (job id, device count).
    Force mode only skips the ping pre-check; SSH host-key and security checks still apply."""
    from apps.devices import selectors as devices
    from apps.core.api import ApiError
    from .jobs import start_job
    targets = devices.devices_with_ids(ids)
    if not targets:
        raise ApiError(400, "No devices selected")
    job_id = start_job(targets, reason="manual-force" if force_ssh else "manual", started_by=started_by)
    if not job_id:
        raise ApiError(409, "A backup is already running. Please wait for it to finish.")
    return job_id, len(targets)


def stop_backup():
    """Stop the running backup (devices that have not started are skipped). Returns the job id."""
    from apps.core.api import ApiError
    from .jobs import cancel_job
    job_id = cancel_job()
    if not job_id:
        raise ApiError(404, "No backup is running")
    return job_id


def delete_version(device, filename):
    storage.delete_file(storage.resolve(device, filename))


def delete_device_backups(device):
    """Delete every saved version of one device folder. Returns (folder name, files deleted)."""
    folder = storage.folder_of(device)
    return folder.name, storage.delete_folders([folder])


def delete_selected_backups(names):
    """Delete every saved version of the chosen devices. Returns (folders, files deleted)."""
    folders = storage.folders_of(names)
    return len(folders), storage.delete_folders(folders)


def delete_all_backups():
    """Delete every backup of every device. Returns the number of files deleted."""
    return storage.delete_folders([f for f in storage.root().iterdir() if f.is_dir()])


# ---------- log housekeeping (called by the scheduler and the background retention task) ----------
def trim_log_table(keep=20000):
    """Keep the log table from growing forever: only the newest `keep` rows stay."""
    newest = BackupLog.objects.order_by("-id").values_list("id", flat=True).first()
    if newest:
        BackupLog.objects.filter(id__lt=newest - keep).delete()


def prune_old_logs(now=None):
    """Delete backup log rows older than the number of months set on the Settings page. Returns rows removed.
    Only the Activity Logs records are removed; saved configuration files and the audit trail stay."""
    from datetime import timedelta
    from apps.scheduling.services import get_setting
    try:
        months = int(get_setting("log_retention_months") or 0)
    except ValueError:
        return 0
    if months <= 0:
        return 0
    cutoff = (now or timezone.now()) - timedelta(days=30 * months)
    removed, _ = BackupLog.objects.filter(ts__lt=cutoff).delete()
    if removed:
        logger.info("Removed %s backup log entries older than %s months", removed, months)
    return removed
