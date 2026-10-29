from __future__ import annotations

import logging
from dataclasses import dataclass

from asgiref.sync import async_to_sync

from orchestrator.exceptions import PluginNotConnectedError
from orchestrator.orchestrator import execute
from workflows.models import SavedWorkflow
from workflows.scheduling import (
    WorkflowScheduleValidationError,
    build_workflow_initial_context,
    validate_workflow_plan,
    resolve_and_validate_inputs,
)

logger = logging.getLogger(__name__)


@dataclass
class WorkflowRunResult:
    status: str
    result: str | None = None
    error_code: str | None = None
    error_detail: str | None = None
    plugin_id: str | None = None


def run_saved_workflow(
    workflow: SavedWorkflow,
    user,
    inputs: dict | None = None,
    on_step=None,
) -> WorkflowRunResult:
    """Validate and execute a saved workflow through the orchestrator."""
    try:
        plan = validate_workflow_plan(workflow.plan)

        resolved_inputs: dict | None = None
        if workflow.input_schema:
            resolved_inputs, input_errors = resolve_and_validate_inputs(
                workflow.input_schema, inputs or {}
            )
            if input_errors:
                return WorkflowRunResult(
                    status="failed",
                    error_code="invalid_inputs",
                    error_detail="; ".join(input_errors),
                )

        initial_context = build_workflow_initial_context(workflow, inputs=resolved_inputs)
        result = async_to_sync(execute)(
            plan,
            user_id=str(user.supabase_uid),
            on_step=on_step,
            initial_context=initial_context,
        )
    except WorkflowScheduleValidationError as exc:
        logger.warning(
            "workflow run validation failed workflow_id=%s user_id=%s error=%s",
            workflow.pk,
            user.pk,
            exc.detail,
        )
        return WorkflowRunResult(status="failed", error_code=exc.code, error_detail=exc.detail)
    except PluginNotConnectedError as exc:
        logger.warning(
            "workflow run plugin missing workflow_id=%s user_id=%s plugin=%s",
            workflow.pk,
            user.pk,
            exc.plugin_id,
        )
        return WorkflowRunResult(
            status="failed",
            error_code="plugin_not_connected",
            error_detail=str(exc),
            plugin_id=exc.plugin_id,
        )
    except Exception as exc:
        logger.exception("workflow run failed workflow_id=%s user_id=%s", workflow.pk, user.pk)
        return WorkflowRunResult(status="failed", error_code="execution_error", error_detail=str(exc))

    return WorkflowRunResult(status="success", result=result)
