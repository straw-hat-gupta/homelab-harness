# Generated manually to remove support for email-only local users.

from django.db import migrations, models


def assert_no_email_only_users(apps, schema_editor):
    User = apps.get_model("authentication", "User")
    count = User.objects.filter(supabase_uid__isnull=True).count()
    if count:
        raise RuntimeError(
            "Cannot make Users.supabase_uid required while email-only users exist. "
            f"Found {count} Users rows with supabase_uid=NULL. Delete or backfill "
            "those rows before applying this migration."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("authentication", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            assert_no_email_only_users,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="user",
            name="supabase_uid",
            field=models.UUIDField(unique=True),
        ),
    ]
