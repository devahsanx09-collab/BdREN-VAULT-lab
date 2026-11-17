"""Explicitly configure global scheduled backups and queue one initial inventory pass."""
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.devices.models import Device
from apps.scheduling.services import put_settings


class Command(BaseCommand):
    help = ("Enable the global backup schedule for all configured devices (monthly on days 1 and 15 "
            "at 02:00 Asia/Dhaka), with 10 concurrent SSH sessions, and queue one initial backup pass.")

    def add_arguments(self, parser):
        parser.add_argument("--confirm-initial-backup", action="store_true",
                            help="Required: allow one initial read-only backup pass across all configured devices.")
        parser.add_argument("--workers", type=int, default=10,
                            help="Concurrent SSH sessions, 1-20; start with 10 on an 8 GB RAM PC.")

    def handle(self, *args, **opts):
        if not opts["confirm_initial_backup"]:
            raise CommandError("No changes made. Re-run with --confirm-initial-backup after checking device credentials and commands.")
        workers = opts["workers"]
        if not 1 <= workers <= 20:
            raise CommandError("--workers must be between 1 and 20; use 10 as the initial setting.")
        count = Device.objects.count()
        if count == 0:
            raise CommandError("No devices are registered. Import/add devices first; no schedule was changed.")
        # Global schedule only. Never edit device credentials, device config, or per-device fields.
        put_settings({
            "workers": str(workers),
            "sched_on": "1",
            "sched_mode": "semimonthly",
            "sched_every": "60",
            "sched_at": "02:00",
            "sched_days": "1,15",
            "sched_catchup": "1",
            "sched_last": str(timezone.now().timestamp()),
            "initial_backup_pending": "1",
            "queued_backup_device_ids": "[]",
        })
        self.stdout.write(self.style.SUCCESS(
            f"Configured {count} device(s): initial backup queued for scheduler; recurring backups on days 1 and 15 at 02:00 Asia/Dhaka; workers={workers}."
        ))
        self.stdout.write("Ensure the background scheduler is running. Initial pass starts on its next tick; offline devices enter failed-device recovery.")
