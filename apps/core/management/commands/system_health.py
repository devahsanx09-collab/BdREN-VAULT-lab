"""Read-only operational checks for the VAULT host."""
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connections
from django.utils import timezone


class Command(BaseCommand):
    help = "Run read-only database, key, backup-folder, and disk-space health checks."

    def handle(self, *args, **opts):
        issues = 0

        def report(label, ok, detail):
            nonlocal issues
            if not ok:
                issues += 1
            style = self.style.SUCCESS if ok else self.style.WARNING
            self.stdout.write(style(f"{'OK' if ok else 'CHECK'} | {label} | {detail}"))

        try:
            connections['default'].ensure_connection()
            with connections['default'].cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            report("database", True, "connection and simple query succeeded")
        except Exception as exc:
            report("database", False, str(exc)[:180])

        data_dir = Path(settings.DATA_DIR)
        backup_dir = Path(settings.BACKUP_DIR)
        key = Path(settings.FERNET_KEY_FILE)
        report("data directory", data_dir.is_dir(), str(data_dir))
        report("backup directory", backup_dir.is_dir() and backup_dir.exists(), str(backup_dir))
        report("encryption key", key.is_file() and key.stat().st_size > 0,
               "key file exists; keep it protected and separately backed up")
        try:
            usage = shutil.disk_usage(backup_dir if backup_dir.exists() else data_dir)
            free_pct = (usage.free / usage.total * 100) if usage.total else 0
            report("disk free space", free_pct >= 15,
                   f"{usage.free / (1024**3):.1f} GiB free ({free_pct:.1f}%); warning threshold 15%")
        except OSError as exc:
            report("disk free space", False, str(exc))
        report("debug mode", not settings.DEBUG, "DEBUG is off" if not settings.DEBUG else "DEBUG is on; turn it off for production")
        report("allowed hosts", settings.ALLOWED_HOSTS != ["*"],
               "explicit host list configured" if settings.ALLOWED_HOSTS != ["*"] else "DJANGO_ALLOWED_HOSTS is wildcard; restrict it before production")
        report("worker limit", 1 <= settings.WORKERS <= settings.MAX_WORKERS, f"WORKERS={settings.WORKERS}; recommended starting value 10; hard cap 20")
        self.stdout.write(f"Health check completed at {timezone.localtime():%Y-%m-%d %H:%M:%S}; checks needing attention: {issues}")
