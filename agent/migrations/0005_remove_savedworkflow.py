from django.db import migrations


class Migration(migrations.Migration):
    """Remove SavedWorkflow state from the agent app (table stays; workflows app takes it over)."""

    dependencies = [
        ('agent', '0004_savedworkflow'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name='SavedWorkflow'),
            ],
            database_operations=[],
        ),
    ]
