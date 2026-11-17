"""Backup jobs: back up many devices in parallel in a background thread, with progress in the database."""
import json
import logging
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timedelta, timezone as dt_timezone

from django.conf import settings
from django.db import InterfaceError, OperationalError, close_old_connections, connections
from django.utils import timezone

from apps.scheduling.services import get_id_list, get_setting, put_settings, update_retry_queue
from apps.core.netguard import resolve_allowed_host

from . import engine
from .models import BackupJob
from .services import STOPPED_MESSAGE, backup_device, finalize_failure

logger = logging.getLogger("dbms")
_START_LOCK = threading.Lock()
_PENDING_KEY = "pending_backup_device_ids"
_QUEUE_KEY = "queued_backup_device_ids"
_HEARTBEAT_KEY = "backup_job_heartbeat"      # "<job id>:<unix time>", written by the running job every few seconds
_CANCEL_KEY = "backup_job_cancel"            # id of the job an operator asked to stop
_PHASE_KEY = "backup_job_phase"              # "<job id>|<text>": e.g. its second pass, shown in the job chip
STALE_AFTER = timedelta(hours=24)            # hard upper limit for one job, whatever its heartbeat says
HEARTBEAT_EVERY = 15                         # seconds between two heartbeats of a running job
HEARTBEAT_STALE = timedelta(minutes=3)       # no heartbeat for this long = the process died (restart, crash, power cut)
TICK = 2                                     # seconds; how often a running job looks for "Stop backup" and writes its heartbeat


def summarize(results):
    """Compact summary of a finished job for the Backup Jobs page (stored in BackupJob.summary).

    counts per status, average seconds per device that finished, the first 20 problem devices with
    their reason, and the ids of every FAILED device (for "Retry these devices")."""
    counts = {"SUCCESS": 0, "UNCHANGED": 0, "FAILED": 0, "CANCELLED": 0}
    secs, problems, failed_ids = [], [], []
    for row in results if isinstance(results, list) else []:
        if not isinstance(row, dict):
            continue
        status = row.get("status")
        status = status if status in counts else "FAILED"
        counts[status] += 1
        if status in ("SUCCESS", "UNCHANGED") and isinstance(row.get("secs"), (int, float)):
            secs.append(float(row["secs"]))
        if status in ("FAILED", "CANCELLED"):
            if status == "FAILED" and str(row.get("device_id", "")).isdigit():
                failed_ids.append(int(row["device_id"]))
            if len(problems) < 20:
                problems.append({"device_id": row.get("device_id"), "ip": row.get("ip", ""), "status": status,
                                 "name": row.get("name") or row.get("hostname") or row.get("ip", ""),
                                 "message": str(row.get("message", ""))[:300]})
    return {"counts": counts, "avg_device_s": round(sum(secs) / len(secs), 1) if secs else None,
            "problems": problems, "failed_ids": failed_ids}


def offline_device_ids(results):
    """Return only devices whose scheduled backup was skipped because ICMP said OFFLINE.

    Authentication, command, host-key, and other SSH failures are not automatically
    retried as reconnect events; they need an operator to fix the underlying problem.
    """
    return {
        int(row["device_id"])
        for row in results
        if isinstance(row, dict)
        and row.get("offline") is True
        and str(row.get("device_id", "")).isdigit()
    }


def _last_seen(job):
    """When the job last proved it is alive: its newest heartbeat, or its creation time before the first one."""
    job_id, _, stamp = str(get_setting(_HEARTBEAT_KEY) or "").partition(":")
    if job_id == job.pk:
        try:
            return max(job.created, datetime.fromtimestamp(float(stamp), tz=dt_timezone.utc))
        except (ValueError, OverflowError, OSError):
            pass
    return job.created


def _beat(job_id):
    """Heartbeat of a running job. A failed write must never stop the backup itself."""
    try:
        put_settings({_HEARTBEAT_KEY: f"{job_id}:{time.time():.0f}"})
    except Exception:
        logger.warning("Job %s heartbeat write failed", job_id, exc_info=True)


def _cancel_requested(job_id):
    try:
        return get_setting(_CANCEL_KEY) == job_id
    except Exception:
        return False


def close_stale_jobs(force=False):
    """Close jobs left unfinished by a crash and persist failed/unattempted devices for recovery.

    A job is dead when it has sent no heartbeat for HEARTBEAT_STALE (the server was restarted or
    crashed while it ran), so "A backup is already running" clears itself after a few minutes
    instead of blocking every backup for a day. `force` closes every unfinished job at once.
    This never sends commands to devices. It only repairs database queue state.
    """
    now = timezone.now()
    stale = [job for job in BackupJob.objects.filter(finished=False)
             if force or now - job.created > STALE_AFTER or now - _last_seen(job) > HEARTBEAT_STALE]
    for job in stale:
        logger.warning("Closing backup job %s: no sign of life (%s of %s devices done)", job.pk, job.done, job.total)
        results = job.results if isinstance(job.results, list) else []
        intended = [int(value) for value in (job.device_ids or []) if str(value).isdigit()]
        try:      # devices it never reached, offline ones and temporary failures are retried later
            update_retry_queue(results, intended=intended)
        except Exception:
            logger.exception("Could not queue the devices of dead job %s for retry", job.pk)
        BackupJob.objects.filter(pk=job.pk, finished=False).update(finished=True, finished_at=now, summary=summarize(results))


def job_running():
    """True while a recent backup job is still working (one job at a time)."""
    close_stale_jobs()
    return BackupJob.objects.filter(finished=False).exists()


def active_job():
    """The job that is running right now, or None."""
    close_stale_jobs()
    return BackupJob.objects.filter(finished=False).order_by("-created").first()


def cancel_job():
    """Ask the running job to stop; returns its id, or None when nothing is running.

    Devices that have not started are skipped. SSH sessions that are already open finish on their own.
    A job whose process is gone (no heartbeat for three beats) is closed immediately.
    """
    job = active_job()
    if job is None:
        return None
    if timezone.now() - _last_seen(job) > timedelta(seconds=HEARTBEAT_EVERY * 3):
        close_stale_jobs(force=True)
    else:
        put_settings({_CANCEL_KEY: job.pk})
    return job.pk


def start_job(devices, reason="", started_by=""):
    """Start one backup job; returns its id, or None when another job is still running."""
    devices = list(devices)
    if not devices:
        return None
    with _START_LOCK:
        if reason == "device-added":
            # A new device's first backup waits only for a job that is running now (not for the retry
            # queue, which may hold devices that stay offline for days).
            if job_running():
                queued = list(dict.fromkeys([*get_id_list(_QUEUE_KEY), *[d.pk for d in devices]]))
                put_settings({_QUEUE_KEY: json.dumps(queued)})
                return "queued"
        elif job_running():
            return None
        job = BackupJob.objects.create(id=uuid.uuid4().hex[:8], total=len(devices),
                                       device_ids=[int(d.pk) for d in devices], reason=str(reason)[:40],
                                       started_by=str(started_by or "")[:150])
        _beat(job.pk)
        # Backup Jobs page: keep the last 200 jobs. Only the newest 20 keep every device result; older ones
        # keep their summary (counts, time, failed devices), which is all the page shows.
        recent = list(BackupJob.objects.order_by("-created").values_list("pk", flat=True)[:250])
        BackupJob.objects.filter(pk__in=recent[200:]).delete()
        BackupJob.objects.filter(pk__in=recent[20:200], finished=True).update(results=[])
    threading.Thread(target=run_job, args=(job.pk, devices, reason), daemon=True, name=f"backup-job-{job.pk}").start()
    return job.pk


def _backup_task(device, reason, preflight=None, abort=None):
    if abort is not None and abort.is_set():          # queued but never started before Stop backup
        return {"device_id": device.pk, "ip": device.ip, "hostname": getattr(device, "name", "") or device.ip,
                "status": "CANCELLED", "message": STOPPED_MESSAGE}
    began = time.monotonic()
    try:
        # First pass of a job: a retryable failure is not written to the database yet (see JobControl).
        defer = bool(getattr(abort, "defer_retryable", False))
        result = (backup_device(device, reason, preflight=preflight, abort=abort, defer_retryable=True) if defer
                  else backup_device(device, reason, preflight=preflight, abort=abort))
        result["secs"] = round(time.monotonic() - began, 1)      # Backup Jobs page + capacity planner
        # Normalize missing identifiers/status so recovery bookkeeping remains reliable.
        if not isinstance(result, dict):
            result = {"status": "FAILED", "message": "Backup returned an invalid result"}
        result.setdefault("device_id", device.pk)
        result.setdefault("ip", device.ip)
        result.setdefault("hostname", getattr(device, "name", "") or device.ip)
        result.setdefault("status", "FAILED")
        return result
    except Exception as exc:
        # A single unexpected device/driver exception must not abort the entire batch.
        logger.exception("Backup task failed for device %s", device.pk)
        return {"device_id": device.pk, "ip": device.ip,
                "hostname": getattr(device, "name", "") or device.ip,
                "status": "FAILED", "message": f"Backup task error: {type(exc).__name__}"}
    finally:
        connections.close_all()           # worker threads close their own database connections


def _update_job(job_id, **fields):
    """Write job progress; survive a dropped MySQL connection (long jobs outlive idle timeouts)."""
    for attempt in range(3):
        try:
            close_old_connections()
            BackupJob.objects.filter(pk=job_id).update(**fields)
            return True
        except (OperationalError, InterfaceError):
            logger.warning("Job %s progress write failed (attempt %s/3); reconnecting",
                                              job_id, attempt + 1, exc_info=True)
            connections.close_all()
            time.sleep(2)
    return False


def _preflight_task(device):
    """Resolve + ping ONE device (runs in the ping pool, so the SSH pool never waits for it)."""
    from apps.monitoring.services import ping_host      # looked up at call time (tests patch it there)
    try:
        target = resolve_allowed_host(device.ip)
        return {"approved_ip": target, "ping": ping_host(target) if target else {"up": False, "ms": None}}
    except Exception:
        return {"approved_ip": None, "ping": {"up": False, "ms": None}}
    finally:
        connections.close_all()


def _unfinished_row(device, status, message):
    return {"device_id": device.pk, "ip": device.ip, "hostname": getattr(device, "name", "") or device.ip,
            "status": status, "message": message}


class JobControl(threading.Event):
    """Set when the job stops early (late answers are then discarded). `defer_retryable` is True during the
    first pass: a temporary failure is then kept out of the database until the second try decides."""
    defer_retryable = False


def _finalize_deferred(results, devices, reason):
    """Write the failures that were held back for the second pass but are final now (no second try ran, it was
    stopped, or it failed too). Nothing about a device reaches the database before its outcome is final."""
    by_id = {int(d.pk): d for d in devices}
    for row in results:
        if isinstance(row, dict) and row.pop("deferred", False) and str(row.get("device_id", "")).isdigit():
            device = by_id.get(int(row["device_id"]))
            if device is not None:
                finalize_failure(device, row.get("name") or device.ip, row.get("message", ""),
                                 row.get("failure", "transient"), reason)


def _set_phase(job_id, text=""):
    """What a running job is doing beyond plain progress (e.g. its second pass), shown in the job chip."""
    try:
        put_settings({_PHASE_KEY: f"{job_id}|{text}" if text else ""})
    except Exception:
        logger.warning("Could not write the phase of job %s", job_id, exc_info=True)


def job_phase(job_id):
    value = str(get_setting(_PHASE_KEY) or "")
    owner, _, text = value.partition("|")
    return text if owner == job_id else ""


def _run_pass(job_id, batch, reason, workers, ping_workers, force, record, stall_limit, abort):
    """One pass over `batch`; every device's result goes to record(result, device).

    Pipeline: every device is resolved and pinged in a small ping pool; as soon as ONE device answers its SSH
    backup is queued on the SSH pool, so a big run starts at once. Offline devices are recorded without ever
    using an SSH worker. Explicit "Force SSH" skips the ping step.
    Returns "" (done), "cancelled" (Stop backup) or "stalled" (no device finished for stall_limit seconds:
    the remaining sessions hang; they are recorded and the pass stops waiting for them)."""
    ssh_pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="dbms-ssh")
    pre_pool = ThreadPoolExecutor(max_workers=ping_workers, thread_name_prefix="dbms-pre")
    stopped = ""
    try:
        pending = {}                     # future -> ("pre" | "ssh", device)
        for device in batch:
            if force:
                pending[ssh_pool.submit(_backup_task, device, reason, None, abort)] = ("ssh", device)
            else:
                pending[pre_pool.submit(_preflight_task, device)] = ("pre", device)

        last_progress = last_beat = last_stop_check = time.monotonic()
        while pending:
            finished, _ = wait(list(pending), timeout=TICK, return_when=FIRST_COMPLETED)
            now = time.monotonic()
            if now - last_beat >= HEARTBEAT_EVERY:
                last_beat = now
                _beat(job_id)
            if finished:
                last_progress = now
            elif now - last_progress > stall_limit:
                stopped = "stalled"
                break
            for future in finished:
                kind, device = pending.pop(future)
                try:
                    value = future.result()
                except Exception as exc:
                    # Defensive boundary: one future must never terminate the batch.
                    value = ({"approved_ip": None, "ping": {"up": False, "ms": None}} if kind == "pre" else
                             {"device_id": device.pk, "ip": device.ip,
                              "hostname": getattr(device, "name", "") or device.ip,
                              "status": "FAILED", "message": f"Worker error: {type(exc).__name__}",
                              "failure": "transient"})
                if kind == "pre":
                    if value["approved_ip"] and value["ping"].get("up"):
                        pending[ssh_pool.submit(_backup_task, device, reason, value, abort)] = ("ssh", device)
                    else:
                        # Offline / invalid target: record it here, no SSH worker is used.
                        record(_backup_task(device, reason, value, abort), device)
                else:
                    record(value, device)
            if now - last_stop_check >= TICK:      # at most one small query every TICK seconds
                last_stop_check = now
                if _cancel_requested(job_id):
                    stopped = "cancelled"
                    break

        if stopped:
            abort.set()                  # before anything else: late answers must not be saved
            logger.warning("Backup job %s %s with %s device(s) unfinished", job_id, stopped, len(pending))
            for future, (kind, device) in list(pending.items()):
                future.cancel()
                record(_unfinished_row(device, "CANCELLED", STOPPED_MESSAGE) if stopped == "cancelled" else
                       dict(_unfinished_row(device, "FAILED", f"The device's backup session gave no answer for "
                                            f"{stall_limit // 60} minutes, so the job stopped waiting. Nothing was "
                                            "saved and the device record was not changed."), failure="transient"),
                       device)
    finally:
        # Normal end: every worker has finished. Stopped early: do not wait for hung sessions.
        ssh_pool.shutdown(wait=not stopped, cancel_futures=bool(stopped))
        pre_pool.shutdown(wait=not stopped, cancel_futures=bool(stopped))
    return stopped


def _second_pass(job_id, results, devices, reason, workers, ping_workers, force, stall_limit, abort):
    """Try again, in the same job, the devices whose failure was temporary (timeout, silence, dropped session,
    login rejected by a busy AAA server): after a cool-down, with few parallel sessions and widely spaced logins.
    A device that now succeeds replaces its failed row. Returns "" or "cancelled" / "stalled"."""
    if not settings.RETRY_PASS:
        return ""
    retry_ids = [int(row["device_id"]) for row in results
                 if isinstance(row, dict) and row.get("status") == "FAILED"
                 and row.get("failure") in ("transient", "auth") and str(row.get("device_id", "")).isdigit()]
    by_id = {int(d.pk): d for d in devices}
    batch = [by_id[i] for i in dict.fromkeys(retry_ids) if i in by_id]
    if not batch:
        return ""
    n = len(batch)
    cooldown = int(settings.RETRY_COOLDOWN)
    _set_phase(job_id, f"Retrying {n} device{'s' if n != 1 else ''} that failed, in {cooldown} s")
    logger.info("Backup job %s: second pass for %s device(s) after %s s", job_id, n, cooldown)
    end = time.monotonic() + cooldown
    while time.monotonic() < end:                       # cool-down; Stop backup still works
        if _cancel_requested(job_id):
            return "cancelled"
        _beat(job_id)
        time.sleep(max(0.0, min(TICK, end - time.monotonic())))
    _set_phase(job_id, f"Retrying {n} device{'s' if n != 1 else ''} that failed")
    index = {int(row["device_id"]): i for i, row in enumerate(results)
             if isinstance(row, dict) and str(row.get("device_id", "")).isdigit()}

    def replace(result, device):
        if result.get("status") == "CANCELLED":         # stopped during the second pass: keep the first result
            return
        result["retried"] = True
        if result.get("status") in ("SUCCESS", "UNCHANGED"):
            result["message"] = ("Succeeded on the automatic second try. " + str(result.get("message") or "")).strip()
        i = index.get(int(device.pk))
        if i is None:
            results.append(result)
        else:
            results[i] = result
        _update_job(job_id, done=len(results), results=list(results))

    with engine.LOGIN_PACER.spacing(3.0):
        return _run_pass(job_id, batch, reason, max(1, min(int(settings.RETRY_PASS_WORKERS), workers)),
                         ping_workers, force, replace, stall_limit, abort)


def run_job(job_id, devices, reason=""):
    """Run one backup job: a first pass over every device, then a second pass for the temporary failures.

    Large inventories: bounded SSH concurrency, a separate ping pool and batched progress writes.
    The job can always end: it writes a heartbeat while it works, stops when an operator presses
    "Stop backup", and gives up on devices whose SSH session hangs past every timeout.
    Afterwards the retry queue is updated (offline and temporarily failed devices are tried again later).
    """
    results = []
    stopped = ""
    try:
        try:
            configured_workers = int(get_setting("workers"))
        except (TypeError, ValueError):
            configured_workers = int(getattr(settings, "WORKERS", 10))
        # Hard safety cap: do not let a stale/tampered setting open hundreds of SSH sessions.
        safe_workers = max(1, min(configured_workers, int(getattr(settings, "MAX_WORKERS", 50))))
        ping_workers = max(1, min(max(int(getattr(settings, "PING_WORKERS", 20)), -(-len(devices) // 16)), 64))
        flush_every = max(1, min(int(getattr(settings, "JOB_PROGRESS_BATCH", 5)), 25))
        # Large runs (500-1000 devices): about 50 progress writes per job instead of one every 5 devices,
        # because each write stores the whole (growing) result list.
        flush_every = max(flush_every, len(devices) // 50)
        force = reason == "manual-force"
        # One device needs at most: a login (second try with double time) + its command (ceiling).
        # Only when NO device at all finishes for this long are the remaining sessions considered hung.
        ssh_timeout = int(getattr(settings, "SSH_TIMEOUT", 30))
        stall_limit = 3 * ssh_timeout + int(getattr(settings, "COMMAND_TIMEOUT", 3600)) + 120

        def add_result(result, device):
            results.append(result)
            if len(results) % flush_every == 0 or len(results) == len(devices):
                _update_job(job_id, done=len(results), results=list(results))

        # Set when the job stops early. SSH sessions that are still open cannot be killed, but a session
        # that answers after this point discards what it read: no file and no database change.
        abort = JobControl()
        abort.defer_retryable = bool(settings.RETRY_PASS)
        stopped = _run_pass(job_id, devices, reason, safe_workers, ping_workers, force, add_result,
                            stall_limit, abort)
        abort.defer_retryable = False         # the second pass is final for every device it tries
        if not stopped:
            stopped = _second_pass(job_id, results, devices, reason, safe_workers, ping_workers, force,
                                   stall_limit, abort)

    except Exception:
        logger.exception("Backup job %s coordinator failed", job_id)
        raise
    finally:
        try:
            _finalize_deferred(results, devices, reason)
        except Exception:
            logger.exception("Could not write the held-back failures of job %s", job_id)
        # Every job (manual or automatic) updates the retry queue: offline devices wait for their ping,
        # temporary failures are retried with back-off, successes and permanent failures leave the queue.
        try:
            update_retry_queue(results, intended=[d.pk for d in devices], cancelled=stopped == "cancelled")
        except Exception:
            logger.exception("Could not update the retry queue")
        _set_phase(job_id, "")
        _update_job(job_id, finished=True, done=len(results), results=results, finished_at=timezone.now(),
                    summary=summarize(results))
        try:
            if get_setting(_CANCEL_KEY) == job_id:
                put_settings({_CANCEL_KEY: ""})
        except Exception:
            logger.warning("Could not clear the stop request of job %s", job_id, exc_info=True)
        connections.close_all()
