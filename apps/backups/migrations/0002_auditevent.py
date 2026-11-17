from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [("backups", "0001_initial")]
    operations = [migrations.CreateModel(
        name="AuditEvent",
        fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("ts", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
            ("username", models.CharField(blank=True, max_length=150)),
            ("action", models.CharField(db_index=True, max_length=80)),
            ("target", models.CharField(blank=True, max_length=255)),
            ("detail", models.TextField(blank=True)),
            ("remote_addr", models.GenericIPAddressField(blank=True, null=True)),
        ],
        options={"ordering": ["-id"]},
    )]
