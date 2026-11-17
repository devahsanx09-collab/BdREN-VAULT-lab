from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("radius", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserDevice",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("username", models.CharField(db_index=True, max_length=64)),
                ("nasname", models.CharField(max_length=128)),
            ],
            options={
                "db_table": "dbms_user_nas",
                "unique_together": {("username", "nasname")},
            },
        ),
    ]
