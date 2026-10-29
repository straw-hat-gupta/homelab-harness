from __future__ import annotations

import logging

from django.http import JsonResponse
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated

from backend.pagination import AivaPagination
from workflows.models import ScheduledRun, ScheduledRunExecution
from workflows.models import compute_next_run_at
from workflows.models import validate_cron_expression, validate_timezone_name
from workflows.models import SavedWorkflow
from workflows.scheduling import WorkflowScheduleValidationError, validate_workflow_schedulable
from workflows.tasks import run_scheduled_run

logger = logging.getLogger(__name__)


def _error(code: str, detail: str) -> dict:
    return {"error": code, "detail": detail}


def _dt(value):
    return value.isoformat() if value else None


def _scheduled_run_data(scheduled_run: ScheduledRun) -> dict:
    workflow = getattr(scheduled_run, "workflow", None)
    return {
        "id": scheduled_run.pk,
        "workflow_id": scheduled_run.workflow_id,
        "workflow_name": workflow.name if workflow else None,
        "name": scheduled_run.name,
        "cron": scheduled_run.cron,
        "timezone": scheduled_run.timezone,
        "enabled": scheduled_run.enabled,
        "next_run_at": _dt(scheduled_run.next_run_at),
        "last_run_at": _dt(scheduled_run.last_run_at),
        "last_status": scheduled_run.last_status,
        "last_error": scheduled_run.last_error,
        "created_at": _dt(scheduled_run.created_at),
        "updated_at": _dt(scheduled_run.updated_at),
    }


def _execution_data(execution: ScheduledRunExecution) -> dict:
    return {
        "id": execution.pk,
        "scheduled_run_id": execution.scheduled_run_id,
        "workflow_id": execution.workflow_id,
        "status": execution.status,
        "started_at": _dt(execution.started_at),
        "finished_at": _dt(execution.finished_at),
        "result": execution.result,
        "error": execution.error,
        "celery_task_id": execution.celery_task_id,
        "created_at": _dt(execution.created_at),
    }


def _validate_schedule(cron: str, timezone_name: str) -> str | None:
    try:
        validate_cron_expression(cron)
        validate_timezone_name(timezone_name)
    except Exception as exc:
        messages = getattr(exc, "messages", None)
        if messages:
            return "; ".join(messages)
        return str(exc)
    return None


def _parse_bool(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    raise ValueError("expected a boolean value")


def _get_owned_workflow(user, workflow_id):
    try:
        return SavedWorkflow.objects.select_related("project").get(pk=workflow_id, user=user)
    except (SavedWorkflow.DoesNotExist, TypeError, ValueError):
        return None


def _validate_workflow_for_schedule(workflow: SavedWorkflow) -> tuple[bool, dict | None]:
    try:
        validate_workflow_schedulable(workflow)
    except WorkflowScheduleValidationError as exc:
        return False, _error(exc.code, exc.detail)
    return True, None


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def scheduled_run_list_view(request):
    if request.method == "GET":
        scheduled_runs = ScheduledRun.objects.select_related("workflow").filter(user=request.user)
        paginator = AivaPagination()
        page = paginator.paginate_queryset(scheduled_runs, request)
        return paginator.get_paginated_response([_scheduled_run_data(item) for item in page])

    workflow_id = request.data.get("workflow_id")
    if not workflow_id:
        return JsonResponse(_error("bad_request", "'workflow_id' is required"), status=400)

    workflow = _get_owned_workflow(request.user, workflow_id)
    if workflow is None:
        return JsonResponse(_error("not_found", "Workflow not found"), status=404)

    ok, validation_error = _validate_workflow_for_schedule(workflow)
    if not ok:
        return JsonResponse(validation_error, status=400)

    cron = request.data.get("cron", "")
    timezone_name = request.data.get("timezone", "UTC") or "UTC"
    schedule_error = _validate_schedule(cron, timezone_name)
    if schedule_error:
        return JsonResponse(_error("invalid_schedule", schedule_error), status=400)

    name = request.data.get("name", "").strip() or workflow.name
    try:
        enabled = _parse_bool(request.data.get("enabled"), True)
    except ValueError as exc:
        return JsonResponse(_error("bad_request", str(exc)), status=400)

    scheduled_run = ScheduledRun.objects.create(
        user=request.user,
        workflow=workflow,
        name=name,
        cron=cron,
        timezone=timezone_name,
        enabled=enabled,
        next_run_at=compute_next_run_at(cron, timezone_name, from_time=timezone.now()),
    )
    return JsonResponse(_scheduled_run_data(scheduled_run), status=201)


@api_view(["GET", "PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def scheduled_run_detail_view(request, scheduled_run_id: int):
    try:
        scheduled_run = ScheduledRun.objects.select_related("workflow", "workflow__project").get(
            pk=scheduled_run_id,
            user=request.user,
        )
    except ScheduledRun.DoesNotExist:
        return JsonResponse(_error("not_found", "Scheduled run not found"), status=404)

    if request.method == "GET":
        return JsonResponse(_scheduled_run_data(scheduled_run))

    if request.method == "DELETE":
        scheduled_run.delete()
        return JsonResponse({"status": "ok", "id": scheduled_run_id})

    if "workflow_id" in request.data:
        workflow = _get_owned_workflow(request.user, request.data["workflow_id"])
        if workflow is None:
            return JsonResponse(_error("not_found", "Workflow not found"), status=404)
        scheduled_run.workflow = workflow

    if "name" in request.data:
        name = request.data["name"].strip()
        if not name:
            return JsonResponse(_error("bad_request", "'name' cannot be blank"), status=400)
        scheduled_run.name = name

    if "cron" in request.data:
        scheduled_run.cron = request.data["cron"]

    if "timezone" in request.data:
        scheduled_run.timezone = request.data["timezone"] or "UTC"

    if "enabled" in request.data:
        try:
            scheduled_run.enabled = _parse_bool(request.data["enabled"], scheduled_run.enabled)
        except ValueError as exc:
            return JsonResponse(_error("bad_request", str(exc)), status=400)

    schedule_error = _validate_schedule(scheduled_run.cron, scheduled_run.timezone)
    if schedule_error:
        return JsonResponse(_error("invalid_schedule", schedule_error), status=400)

    ok, validation_error = _validate_workflow_for_schedule(scheduled_run.workflow)
    if not ok:
        return JsonResponse(validation_error, status=400)

    if any(field in request.data for field in ("cron", "timezone", "enabled")):
        scheduled_run.next_run_at = compute_next_run_at(
            scheduled_run.cron,
            scheduled_run.timezone,
            from_time=timezone.now(),
        )

    scheduled_run.save()
    return JsonResponse(_scheduled_run_data(scheduled_run))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def scheduled_run_now_view(request, scheduled_run_id: int):
    try:
        scheduled_run = ScheduledRun.objects.select_related("workflow", "workflow__project").get(
            pk=scheduled_run_id,
            user=request.user,
        )
    except ScheduledRun.DoesNotExist:
        return JsonResponse(_error("not_found", "Scheduled run not found"), status=404)

    ok, validation_error = _validate_workflow_for_schedule(scheduled_run.workflow)
    if not ok:
        return JsonResponse(validation_error, status=400)

    execution = ScheduledRunExecution.objects.create(
        scheduled_run=scheduled_run,
        workflow=scheduled_run.workflow,
        status="queued",
    )
    try:
        async_result = run_scheduled_run.delay(execution.pk)
    except Exception as exc:
        error = f"queue_unavailable: {exc}"
        logger.warning(
            "scheduled run-now enqueue failed run_id=%s execution_id=%s error=%s",
            scheduled_run.pk,
            execution.pk,
            error,
        )
        now = timezone.now()
        execution.status = "failed"
        execution.finished_at = now
        execution.error = error
        execution.save(update_fields=["status", "finished_at", "error"])
        scheduled_run.last_run_at = now
        scheduled_run.last_status = "failed"
        scheduled_run.last_error = error
        scheduled_run.save(update_fields=["last_run_at", "last_status", "last_error", "updated_at"])
        return JsonResponse(_error("queue_unavailable", str(exc)), status=503)

    task_id = getattr(async_result, "id", "") or ""
    if task_id:
        execution.celery_task_id = task_id
        execution.save(update_fields=["celery_task_id"])

    return JsonResponse({"execution": _execution_data(execution)}, status=202)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def scheduled_run_executions_view(request, scheduled_run_id: int):
    try:
        scheduled_run = ScheduledRun.objects.get(pk=scheduled_run_id, user=request.user)
    except ScheduledRun.DoesNotExist:
        return JsonResponse(_error("not_found", "Scheduled run not found"), status=404)

    executions = ScheduledRunExecution.objects.filter(scheduled_run=scheduled_run)
    paginator = AivaPagination()
    page = paginator.paginate_queryset(executions, request)
    return paginator.get_paginated_response([_execution_data(item) for item in page])
