from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("backups", "0006_backuplog_kind"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="backuplog",
            name="kind",
        ),
    ]
