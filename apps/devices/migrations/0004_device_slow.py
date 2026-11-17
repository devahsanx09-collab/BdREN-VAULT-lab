from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("devices", "0003_device_creator_audit"),
    ]

    operations = [
        migrations.AddField(
            model_name="device",
            name="slow",
            field=models.BooleanField(default=False, help_text="Give this device more time and gentler, "
                                      "paced commands (for old/weak hardware or a poor link). Never sends "
                                      "extra commands; it only waits longer and reads more slowly."),
        ),
    ]
