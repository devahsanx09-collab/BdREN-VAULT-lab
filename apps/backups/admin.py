from django.contrib import admin

from .models import BackupLog


@admin.register(BackupLog)
class BackupLogAdmin(admin.ModelAdmin):
    list_display = ("ts", "ip", "name", "status", "message")
    list_filter = ("status",)
    search_fields = ("ip", "name", "message")
