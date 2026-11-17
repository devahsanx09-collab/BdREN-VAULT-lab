from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("devices", "0004_device_slow"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="device",
            name="slow",
        ),
    ]
