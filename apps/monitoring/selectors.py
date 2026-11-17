"""Monitoring - read layer: the Dashboard numbers and server health.

Backup and device numbers come from those apps' selectors; this module only combines them.
"""
import logging
import shutil
from datetime import timedelta

from django.conf import settings
from django.db import connection
from django.utils import timezone

from apps.backups import selectors as backups
from apps.backups.jobs import job_running
from apps.core.utils import fmt_dt
from apps.devices import selectors as devices
from apps.devices.vendors import VENDORS
from apps.scheduling import services as scheduling

from .models import PingHistory


def database_info():
    """Size of the application database (MySQL / MariaDB) for the Dashboard card."""
    name = str(settings.DATABASES["default"].get("NAME", ""))
    try:
        if connection.vendor == "mysql":
            with connection.cursor() as cur:
                cur.execute("SELECT COALESCE(SUM(data_length + index_length), 0) "
                            "FROM information_schema.tables WHERE table_schema = DATABASE()")
                return {"engine": "MySQL / MariaDB", "name": name, "bytes": int(cur.fetchone()[0] or 0)}
    except Exception:
        logging.getLogger("dbms").warning("Could not read the database size", exc_info=True)
    return {"engine": connection.vendor, "name": name, "bytes": None}


def disk_health():
    """Free space where the backups are stored (no recursive scan: cheap on every refresh)."""
    disk_path = settings.BACKUP_DIR if settings.BACKUP_DIR.exists() else settings.DATA_DIR
    try:
        disk = shutil.disk_usage(str(disk_path))
        return {"total_bytes": disk.total, "free_bytes": disk.free,
                "used_percent": round((disk.used / disk.total) * 100, 1) if disk.total else 0,
                "status": "critical" if disk.free < 2 * 1024**3 or (disk.total and disk.free / disk.total < .05)
                          else "warning" if disk.total and disk.free / disk.total < .15 else "ok"}
    except OSError:
        return {"total_bytes": 0, "free_bytes": 0, "used_percent": None, "status": "unknown"}


def ping_history(hours=24):
    return [{"ts": fmt_dt(p.ts), "total": p.total, "up": p.up, "avg_ms": p.avg_ms}
            for p in PingHistory.objects.filter(ts__gte=timezone.now() - timedelta(hours=hours))]


def dashboard(show_internals):
    """Numbers for the Dashboard: backups per day, uptime history, vendors, results, schedule and health.
    show_internals=False (non-administrators) hides the database engine and name."""
    today = timezone.localdate()
    per_day = backups.results_per_day([today - timedelta(days=i) for i in range(13, -1, -1)])
    vendors, status, total = {}, {"SUCCESS": 0, "UNCHANGED": 0, "FAILED": 0, "NONE": 0}, 0
    for device_type, last_status in devices.type_and_status():
        total += 1
        group = VENDORS[device_type].group if device_type in VENDORS else "Other"
        vendors[group] = vendors.get(group, 0) + 1
        status[last_status if last_status in status else "NONE"] += 1
    values = scheduling.all_settings()
    db_info = database_info()
    last_good = backups.last_good_backup_time()
    health = {"disk": disk_health(), "database_bytes": db_info["bytes"],
              "database_engine": db_info["engine"] if show_internals else "Database",
              "database_name": db_info["name"] if show_internals else "",
              "backup_dir_exists": settings.BACKUP_DIR.is_dir(),
              "last_success": fmt_dt(last_good) if last_good else "Never",
              "failed_24h": backups.failed_since(24)}
    return {"days": [{"d": k, **v} for k, v in per_day.items()], "ping": ping_history(), "status": status,
            "vendors": sorted(vendors.items(), key=lambda x: -x[1]), "total": total,
            "sched_on": values["sched_on"] == "1",
            "next_run": scheduling.next_scheduled_run(values),
            "ping_seconds": settings.PING_SECONDS, "job_running": job_running(),
            "health": health}
