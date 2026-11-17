from django.db import models
from django.utils import timezone


class Status(models.TextChoices):
    SUCCESS = "SUCCESS", "Saved a new backup"
    UNCHANGED = "UNCHANGED", "No change since last backup"
    FAILED = "FAILED", "Failed"


class BackupLog(models.Model):
    """One line of the Logs tab: the result of one device backup."""
    ts = models.DateTimeField(default=timezone.now, db_index=True)
    ip = models.CharField(max_length=253)
    name = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices)
    message = models.TextField(blank=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"{self.ts:%Y-%m-%d %H:%M} {self.ip} {self.status}"


class BackupJob(models.Model):
    """Progress of one 'back up these devices' run. Stored in the database so every process can see it."""
    id = models.CharField(max_length=8, primary_key=True)
    total = models.PositiveIntegerField()
    done = models.PositiveIntegerField(default=0)
    finished = models.BooleanField(default=False)
    results = models.JSONField(default=list)
    # Persist the intended workload so unfinished devices can be recovered after a crash.
    device_ids = models.JSONField(default=list)
    reason = models.CharField(max_length=40, blank=True)
    created = models.DateTimeField(auto_now_add=True)
    # Backup Jobs page: how long the run took and who started it ("" = the scheduler / system).
    finished_at = models.DateTimeField(null=True, blank=True)
    started_by = models.CharField(max_length=150, blank=True, default="")
    # Small summary written when the job ends (counts, average time, failed devices), so the Backup Jobs
    # page never has to re-read every device result of every job (jobs.summarize()).
    summary = models.JSONField(default=dict, blank=True)


class AuditEvent(models.Model):
    """Append-only record of security-relevant operator actions."""
    ts = models.DateTimeField(default=timezone.now, db_index=True)
    username = models.CharField(max_length=150, blank=True)
    action = models.CharField(max_length=80, db_index=True)
    target = models.CharField(max_length=255, blank=True)
    detail = models.TextField(blank=True)
    remote_addr = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"{self.ts:%Y-%m-%d %H:%M} {self.username} {self.action}"
