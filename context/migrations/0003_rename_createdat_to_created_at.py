from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('context', '0002_rename_created_at_projectcontext_createdat'),
    ]

    operations = [
        migrations.RenameField(
            model_name='projectcontext',
            old_name='createdAt',
            new_name='created_at',
        ),
    ]
