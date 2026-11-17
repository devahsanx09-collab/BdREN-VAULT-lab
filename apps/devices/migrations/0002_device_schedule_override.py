from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("devices", "0001_initial")]
    operations = [
        migrations.AddField(model_name="device", name="schedule_override", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="device", name="schedule_days", field=models.CharField(default="1,15", max_length=100)),
        migrations.AddField(model_name="device", name="schedule_time", field=models.CharField(default="02:00", max_length=5)),
        migrations.AddField(model_name="device", name="schedule_last_date", field=models.CharField(blank=True, default="", max_length=10)),
    ]
