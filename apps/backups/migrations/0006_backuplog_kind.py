from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("backups", "0005_backupjob_summary"),
    ]

    operations = [
        migrations.AddField(
            model_name="backuplog",
            name="kind",
            field=models.CharField(blank=True, default="", max_length=20),
        ),
    ]
