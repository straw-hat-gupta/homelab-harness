from django.db import migrations


class Migration(migrations.Migration):
    """Squash of 0002 (created_at→createdAt) and 0003 (createdAt→created_at).
    The net effect is identity; this no-op squash keeps new installs clean."""

    replaces = [
        ('context', '0002_rename_created_at_projectcontext_createdat'),
        ('context', '0003_rename_createdat_to_created_at'),
    ]

    dependencies = [('context', '0001_initial')]

    operations = []
