from django.db import models
from django.utils import timezone


class PingHistory(models.Model):
    """One round of the background ping monitor (feeds the Dashboard uptime graph, kept 7 days)."""
    ts = models.DateTimeField(default=timezone.now, db_index=True)
    total = models.PositiveIntegerField()
    up = models.PositiveIntegerField()
    avg_ms = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ["id"]
