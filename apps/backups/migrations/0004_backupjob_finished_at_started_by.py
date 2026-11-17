from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("backups", "0003_backupjob_recovery_metadata"),
    ]

    operations = [
        migrations.AddField(
            model_name="backupjob",
            name="finished_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="backupjob",
            name="started_by",
            field=models.CharField(blank=True, default="", max_length=150),
        ),
    ]
