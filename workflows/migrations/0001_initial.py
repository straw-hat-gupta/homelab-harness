import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Adopt the existing saved_workflows table (created by agent 0004) into the workflows app."""

    initial = True

    dependencies = [
        ('agent', '0005_remove_savedworkflow'),
        ('projects', '0004_add_system_prompt'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='SavedWorkflow',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('name', models.CharField(max_length=255)),
                        ('description', models.TextField(blank=True)),
                        ('plan', models.JSONField()),
                        ('created_at', models.DateTimeField(auto_now_add=True)),
                        ('updated_at', models.DateTimeField(auto_now=True)),
                        ('project', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='saved_workflows', to='projects.projects')),
                        ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='saved_workflows', to=settings.AUTH_USER_MODEL)),
                    ],
                    options={
                        'db_table': 'saved_workflows',
                        'ordering': ['-updated_at'],
                        'indexes': [models.Index(fields=['user', '-updated_at'], name='saved_workf_user_id_e7dec1_idx')],
                    },
                ),
            ],
            database_operations=[],
        ),
    ]
