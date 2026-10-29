from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0002_remove_projects_contextid_projects_activecontextfrom_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="projects",
            name="pending_plan",
            field=models.JSONField(blank=True, default=None, null=True),
        ),
    ]
