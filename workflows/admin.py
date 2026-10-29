from django.contrib import admin

from .models import SavedWorkflow, ScheduledRun, ScheduledRunExecution


@admin.register(SavedWorkflow)
class SavedWorkflowAdmin(admin.ModelAdmin):
    list_display = ("user", "name", "project", "updated_at")
    ordering = ("-updated_at",)
    readonly_fields = ("user", "created_at", "updated_at")
    search_fields = ("user__email", "name")


@admin.register(ScheduledRun)
class ScheduledRunAdmin(admin.ModelAdmin):
    list_display = ("user", "name", "workflow", "enabled", "next_run_at", "last_status")
    list_filter = ("enabled", "last_status")
    ordering = ("next_run_at",)
    readonly_fields = ("created_at", "updated_at", "last_run_at", "last_status", "last_error")
    search_fields = ("user__email", "name", "workflow__name")


@admin.register(ScheduledRunExecution)
class ScheduledRunExecutionAdmin(admin.ModelAdmin):
    list_display = ("scheduled_run", "workflow", "status", "started_at", "finished_at", "created_at")
    list_filter = ("status",)
    ordering = ("-created_at",)
    readonly_fields = ("created_at", "started_at", "finished_at", "result", "error", "celery_task_id")
    search_fields = ("scheduled_run__name", "scheduled_run__user__email", "workflow__name")
