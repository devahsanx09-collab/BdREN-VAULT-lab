from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("radius", "0002_userdevice"),
    ]

    operations = [
        migrations.CreateModel(
            name="NasRole",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nasname", models.CharField(max_length=128, unique=True)),
                ("role", models.CharField(default="other", max_length=30)),
            ],
            options={
                "db_table": "dbms_nas_role",
            },
        ),
    ]
