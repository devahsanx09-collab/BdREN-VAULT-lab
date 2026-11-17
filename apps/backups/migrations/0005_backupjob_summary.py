from django.db import migrations, models


def fill_summaries(apps, schema_editor):
    """Give jobs that finished before this version their summary, so the Backup Jobs page can list them."""
    from apps.backups.jobs import summarize
    BackupJob = apps.get_model("backups", "BackupJob")
    for job in BackupJob.objects.filter(finished=True):
        BackupJob.objects.filter(pk=job.pk).update(summary=summarize(job.results))


class Migration(migrations.Migration):

    dependencies = [
        ("backups", "0004_backupjob_finished_at_started_by"),
    ]

    operations = [
        migrations.AddField(
            model_name="backupjob",
            name="summary",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.RunPython(fill_summaries, migrations.RunPython.noop),
    ]
