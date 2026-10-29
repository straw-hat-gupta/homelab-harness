from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('contacts', '0002_contactconnection_externalid_scoped_unique'),
    ]

    operations = [
        migrations.RenameField(
            model_name='contact',
            old_name='firstName',
            new_name='first_name',
        ),
        migrations.RenameField(
            model_name='contact',
            old_name='lastName',
            new_name='last_name',
        ),
        migrations.RenameField(
            model_name='contact',
            old_name='createdAt',
            new_name='created_at',
        ),
        migrations.RenameField(
            model_name='contactconnection',
            old_name='externalId',
            new_name='external_id',
        ),
        migrations.AlterUniqueTogether(
            name='contactconnection',
            unique_together={('contact', 'service', 'external_id')},
        ),
    ]
