from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("radius", "0003_nasrole"),
    ]

    operations = [
        migrations.AlterField(
            model_name="nasrole",
            name="role",
            field=models.CharField(default="Other", max_length=50),
        ),
    ]
