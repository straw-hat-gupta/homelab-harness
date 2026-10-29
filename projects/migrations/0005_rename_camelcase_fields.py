from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0004_add_system_prompt'),
    ]

    operations = [
        migrations.RenameField(
            model_name='projects',
            old_name='createdAt',
            new_name='created_at',
        ),
        migrations.RenameField(
            model_name='projects',
            old_name='updatedAt',
            new_name='updated_at',
        ),
        migrations.RenameField(
            model_name='projects',
            old_name='activeContextFrom',
            new_name='active_context_from',
        ),
    ]
