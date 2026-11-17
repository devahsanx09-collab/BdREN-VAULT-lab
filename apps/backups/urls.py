from django.urls import path

from . import views

# Fixed words (download, delete, delete-all) come BEFORE the <device> patterns so they win.
urlpatterns = [
    path("api/backup", views.start_backup, name="api-backup-start"),
    path("api/jobs/active", views.job_active, name="api-job-active"),
    path("api/jobs/history", views.jobs_history, name="api-jobs-history"),
    path("api/logs/summary", views.logs_summary, name="api-logs-summary"),
    path("api/jobs/cancel", views.job_cancel, name="api-job-cancel"),
    path("api/jobs/<str:job_id>", views.job_status, name="api-job"),
    path("api/logs", views.logs, name="api-logs"),
    path("api/reports/compliance.csv", views.compliance_report, name="api-compliance-report"),
    path("api/reports/changes", views.change_report, name="api-change-report"),
    path("api/audit", views.audit_events, name="api-audit-events"),
    path("api/alerts", views.alerts, name="api-backup-alerts"),
    path("api/notifications", views.notifications, name="api-notifications"),
    path("api/backups", views.backups, name="api-backups"),
    path("api/backups/download", views.download_selected, name="api-backups-download"),
    path("api/backups/delete", views.delete_selected, name="api-backups-delete"),
    path("api/backups/delete-all", views.delete_all_backups, name="api-backups-delete-all"),
    path("api/backup-tree/<int:device_id>", views.device_backup_tree, name="api-device-backup-tree"),
    path("api/backups/<str:device>", views.device_backups, name="api-device-backups"),
    path("api/backups/<str:device>/<path:filename>", views.backup_file, name="api-backup-file"),
    path("api/diff/<str:device>", views.diff, name="api-diff"),
    path("api/download-all", views.download_all, name="api-download-all"),
]
