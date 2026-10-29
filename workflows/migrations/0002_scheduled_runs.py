import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workflows", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ScheduledRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                ("cron", models.CharField(max_length=100)),
                ("timezone", models.CharField(default="UTC", max_length=64)),
                ("enabled", models.BooleanField(default=True)),
                ("next_run_at", models.DateTimeField(db_index=True)),
                ("last_run_at", models.DateTimeField(blank=True, null=True)),
                (
                    "last_status",
                    models.CharField(
                        blank=True,
                        choices=[("", ""), ("success", "Success"), ("failed", "Failed"), ("skipped", "Skipped")],
                        default="",
                        max_length=20,
                    ),
                ),
                ("last_error", models.TextField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="scheduled_runs", to=settings.AUTH_USER_MODEL),
                ),
                (
                    "workflow",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="scheduled_runs", to="workflows.savedworkflow"),
                ),
            ],
            options={
                "db_table": "scheduled_runs",
                "ordering": ["next_run_at"],
                "indexes": [
                    models.Index(fields=["user", "enabled", "next_run_at"], name="scheduled_r_user_id_c101d5_idx"),
                    models.Index(fields=["workflow"], name="scheduled_r_workflo_d3eb8f_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="ScheduledRunExecution",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("queued", "Queued"),
                            ("running", "Running"),
                            ("success", "Success"),
                            ("failed", "Failed"),
                            ("skipped", "Skipped"),
                        ],
                        default="queued",
                        max_length=20,
                    ),
                ),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("result", models.JSONField(blank=True, null=True)),
                ("error", models.TextField(blank=True, null=True)),
                ("celery_task_id", models.CharField(blank=True, max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "scheduled_run",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="executions", to="workflows.scheduledrun"),
                ),
                (
                    "workflow",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="scheduled_executions",
                        to="workflows.savedworkflow",
                    ),
                ),
            ],
            options={
                "db_table": "scheduled_run_executions",
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(fields=["scheduled_run", "-created_at"], name="scheduled_r_schedul_aac29d_idx"),
                    models.Index(fields=["status"], name="scheduled_r_status_0b0e17_idx"),
                ],
            },
        ),
    ]
