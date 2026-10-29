from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0003_task_status_choices'),
    ]

    operations = [
        migrations.RenameField(
            model_name='task',
            old_name='createdAt',
            new_name='created_at',
        ),
        migrations.RenameField(
            model_name='task',
            old_name='updatedAt',
            new_name='updated_at',
        ),
        migrations.RenameField(
            model_name='subtask',
            old_name='createdAt',
            new_name='created_at',
        ),
    ]
