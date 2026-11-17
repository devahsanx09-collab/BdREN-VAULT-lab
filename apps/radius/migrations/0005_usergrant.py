from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("radius", "0004_alter_nasrole_role"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserGrant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("username", models.CharField(db_index=True, max_length=64)),
                ("kind", models.CharField(max_length=10)),
                ("value", models.CharField(max_length=128)),
            ],
            options={
                "db_table": "dbms_user_grant",
                "unique_together": {("username", "kind", "value")},
            },
        ),
    ]
