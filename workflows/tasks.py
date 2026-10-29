from __future__ import annotations

import logging
from typing import Any

from celery import shared_task
from django.db import connection, transaction
from django.utils import timezone

from workflows.models import ScheduledRun, ScheduledRunExecution
from workflows.runner import run_saved_workflow
from workflows.scheduling import WorkflowScheduleValidationError, validate_workflow_schedulable

logger = logging.getLogger(__name__)


def _mark_execution_finished(
    execution: ScheduledRunExecution,
    scheduled_run: ScheduledRun,
    status: str,
    result: Any = None,
    error: str | None = None,
) -> dict:
    finished_at = timezone.now()
    execution.status = status
    execution.finished_at = finished_at
    execution.result = result
    execution.error = error
    execution.save(update_fields=["status", "finished_at", "result", "error"])

    scheduled_run.last_run_at = finished_at
    scheduled_run.last_status = status if status in {"success", "failed", "skipped"} else ""
    scheduled_run.last_error = error
    scheduled_run.save(update_fields=["last_run_at", "last_status", "last_error", "updated_at"])

    return {"execution_id": execution.pk, "status": status, "error": error}


@shared_task(name="workflows.dispatch_due_scheduled_runs")
def dispatch_due_scheduled_runs(limit: int = 100) -> dict:
    """Find due scheduled runs, advance them, and enqueue execution tasks."""
    now = timezone.now()
    queued_execution_ids: list[int] = []

    with transaction.atomic():
        queryset = (
            ScheduledRun.objects.filter(enabled=True, next_run_at__lte=now)
            .select_related("workflow")
            .order_by("next_run_at", "id")
        )
        if connection.features.has_select_for_update:
            queryset = queryset.select_for_update(
                skip_locked=connection.features.has_select_for_update_skip_locked
            )

        for scheduled_run in list(queryset[:limit]):
            execution = ScheduledRunExecution.objects.create(
                scheduled_run=scheduled_run,
                workflow=scheduled_run.workflow,
                status="queued",
            )
            queued_execution_ids.append(execution.pk)

            scheduled_run.next_run_at = scheduled_run.compute_next_run_at(from_time=now)
            scheduled_run.save(update_fields=["next_run_at", "updated_at"])

    celery_task_ids: dict[int, str] = {}
    failed_to_queue_ids: list[int] = []
    for execution_id in queued_execution_ids:
        try:
            async_result = run_scheduled_run.delay(execution_id)
        except Exception as exc:
            failed_to_queue_ids.append(execution_id)
            try:
                execution = ScheduledRunExecution.objects.select_related("scheduled_run").get(pk=execution_id)
            except ScheduledRunExecution.DoesNotExist:
                logger.exception("scheduled run execution disappeared before enqueue id=%s", execution_id)
                continue
            error = f"queue_unavailable: {exc}"
            logger.warning("scheduled run enqueue failed execution_id=%s error=%s", execution_id, error)
            _mark_execution_finished(execution, execution.scheduled_run, "failed", error=error)
            continue

        task_id = getattr(async_result, "id", "") or ""
        celery_task_ids[execution_id] = task_id
        if task_id:
            ScheduledRunExecution.objects.filter(pk=execution_id).update(celery_task_id=task_id)

    logger.info(
        "scheduled runs dispatched count=%d failed_to_queue=%d",
        len(celery_task_ids),
        len(failed_to_queue_ids),
    )
    return {
        "queued": len(celery_task_ids),
        "failed_to_queue": len(failed_to_queue_ids),
        "execution_ids": list(celery_task_ids.keys()),
        "failed_execution_ids": failed_to_queue_ids,
        "task_ids": celery_task_ids,
    }


def execute_scheduled_run(execution_id: int, celery_task_id: str = "") -> dict:
    """Execute one queued scheduled workflow and persist its terminal state."""
    try:
        execution = ScheduledRunExecution.objects.select_related(
            "scheduled_run__user",
            "scheduled_run__workflow__project",
            "workflow",
        ).get(pk=execution_id)
    except ScheduledRunExecution.DoesNotExist:
        logger.warning("scheduled run execution missing id=%s", execution_id)
        return {"execution_id": execution_id, "status": "missing", "error": "execution not found"}

    scheduled_run = execution.scheduled_run
    started_at = timezone.now()
    execution.status = "running"
    execution.started_at = started_at
    if celery_task_id and not execution.celery_task_id:
        execution.celery_task_id = celery_task_id
    execution.save(update_fields=["status", "started_at", "celery_task_id"])

    if not scheduled_run.enabled:
        return _mark_execution_finished(
            execution,
            scheduled_run,
            "skipped",
            error="Scheduled run is disabled.",
        )

    workflow = scheduled_run.workflow
    try:
        validate_workflow_schedulable(workflow)
    except WorkflowScheduleValidationError as exc:
        error = f"{exc.code}: {exc.detail}"
        logger.warning(
            "scheduled run validation failed run_id=%s execution_id=%s error=%s",
            scheduled_run.pk,
            execution.pk,
            error,
        )
        return _mark_execution_finished(execution, scheduled_run, "failed", error=error)

    run_result = run_saved_workflow(workflow, scheduled_run.user)
    if run_result.status != "success":
        error = f"{run_result.error_code}: {run_result.error_detail}"
        logger.warning(
            "scheduled run failed run_id=%s execution_id=%s error=%s",
            scheduled_run.pk,
            execution.pk,
            error,
        )
        return _mark_execution_finished(execution, scheduled_run, "failed", error=error)

    logger.info("scheduled run execution succeeded run_id=%s execution_id=%s", scheduled_run.pk, execution.pk)
    return _mark_execution_finished(execution, scheduled_run, "success", result=run_result.result)


@shared_task(bind=True, name="workflows.run_scheduled_run")
def run_scheduled_run(self, execution_id: int) -> dict:
    return execute_scheduled_run(execution_id, celery_task_id=getattr(self.request, "id", "") or "")
