from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workflows", "0002_scheduled_runs"),
    ]

    operations = [
        migrations.AddField(
            model_name="savedworkflow",
            name="input_schema",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
