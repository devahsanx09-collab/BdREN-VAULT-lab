from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("backups", "0002_auditevent")]

    operations = [
        migrations.AddField(
            model_name="backupjob",
            name="device_ids",
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name="backupjob",
            name="reason",
            field=models.CharField(blank=True, max_length=40),
        ),
    ]
