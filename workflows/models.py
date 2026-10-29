import datetime as dt
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone as dj_timezone
from croniter import croniter

User = get_user_model()


SCHEDULED_RUN_LAST_STATUS_CHOICES = [
    ("", ""),
    ("success", "Success"),
    ("failed", "Failed"),
    ("skipped", "Skipped"),
]

SCHEDULED_RUN_EXECUTION_STATUS_CHOICES = [
    ("queued", "Queued"),
    ("running", "Running"),
    ("success", "Success"),
    ("failed", "Failed"),
    ("skipped", "Skipped"),
]


class SavedWorkflow(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="saved_workflows")
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    plan = models.JSONField()
    input_schema = models.JSONField(default=list, blank=True)
    project = models.ForeignKey(
        "projects.Projects", null=True, blank=True, on_delete=models.SET_NULL, related_name="saved_workflows"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "saved_workflows"
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["user", "-updated_at"])]

    def __str__(self):
        return f"{self.user_id}:{self.name}"


def validate_cron_expression(value: str) -> None:
    """Validate a five-field cron expression."""
    if not value or not isinstance(value, str) or not croniter.is_valid(value):
        raise ValidationError("cron must be a valid cron expression")


def validate_timezone_name(value: str) -> None:
    """Validate an IANA timezone name."""
    try:
        ZoneInfo(value)
    except (TypeError, ZoneInfoNotFoundError):
        raise ValidationError("timezone must be a valid IANA timezone name")


def compute_next_run_at(cron: str, timezone_name: str = "UTC", from_time=None):
    """Compute the next run time in UTC for a cron expression and timezone."""
    validate_cron_expression(cron)
    validate_timezone_name(timezone_name)

    tz = ZoneInfo(timezone_name)
    base = from_time or dj_timezone.now()
    if dj_timezone.is_naive(base):
        base = dj_timezone.make_aware(base, dt.timezone.utc)

    local_base = base.astimezone(tz)
    next_local = croniter(cron, local_base).get_next(dt.datetime)
    if dj_timezone.is_naive(next_local):
        next_local = dj_timezone.make_aware(next_local, tz)
    return next_local.astimezone(dt.timezone.utc)


class ScheduledRun(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="scheduled_runs")
    workflow = models.ForeignKey(
        SavedWorkflow,
        on_delete=models.CASCADE,
        related_name="scheduled_runs",
    )
    name = models.CharField(max_length=255)
    cron = models.CharField(max_length=100)
    timezone = models.CharField(max_length=64, default="UTC")
    enabled = models.BooleanField(default=True)
    next_run_at = models.DateTimeField(db_index=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(
        max_length=20,
        blank=True,
        default="",
        choices=SCHEDULED_RUN_LAST_STATUS_CHOICES,
    )
    last_error = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "scheduled_runs"
        ordering = ["next_run_at"]
        indexes = [
            models.Index(fields=["user", "enabled", "next_run_at"]),
            models.Index(fields=["workflow"]),
        ]

    def clean(self):
        validate_cron_expression(self.cron)
        validate_timezone_name(self.timezone)

    def save(self, *args, **kwargs):
        if not self.next_run_at:
            self.next_run_at = compute_next_run_at(self.cron, self.timezone)
        super().save(*args, **kwargs)

    def compute_next_run_at(self, from_time=None):
        return compute_next_run_at(self.cron, self.timezone, from_time=from_time)

    def __str__(self):
        return f"{self.user_id}:{self.name}"


class ScheduledRunExecution(models.Model):
    scheduled_run = models.ForeignKey(
        ScheduledRun,
        on_delete=models.CASCADE,
        related_name="executions",
    )
    workflow = models.ForeignKey(
        SavedWorkflow,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="scheduled_executions",
    )
    status = models.CharField(
        max_length=20,
        choices=SCHEDULED_RUN_EXECUTION_STATUS_CHOICES,
        default="queued",
    )
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    result = models.JSONField(null=True, blank=True)
    error = models.TextField(null=True, blank=True)
    celery_task_id = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "scheduled_run_executions"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["scheduled_run", "-created_at"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"{self.scheduled_run_id}:{self.status}"
