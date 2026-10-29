"""
Workflow management tools — allow the planner to save and list reusable workflows.
"""
import logging
from typing import Any, Dict, List, Optional

from asgiref.sync import sync_to_async

from tools.registry import ToolDef, register

logger = logging.getLogger(__name__)


@sync_to_async
def _save_workflow(
    user_id: str,
    name: str,
    plan: dict,
    description: str,
    input_schema: list,
) -> Dict[str, Any]:
    from django.contrib.auth import get_user_model
    from workflows.models import SavedWorkflow
    from workflows.scheduling import validate_workflow_plan, validate_plan_deep, validate_input_schema

    User = get_user_model()
    user = User.objects.get(supabase_uid=user_id)

    try:
        parsed_plan = validate_workflow_plan(plan)
    except Exception as exc:
        return {"status": "error", "detail": f"Invalid plan: {exc}"}

    deep_errors = validate_plan_deep(parsed_plan)
    if deep_errors:
        return {"status": "error", "detail": "; ".join(deep_errors)}

    if input_schema:
        schema_errors = validate_input_schema(input_schema)
        if schema_errors:
            return {"status": "error", "detail": "; ".join(schema_errors)}

    wf = SavedWorkflow.objects.create(
        user=user,
        name=name,
        description=description,
        plan=plan,
        input_schema=input_schema,
    )
    logger.info("workflow.save user_id=%s workflow_id=%s name=%r", user_id, wf.pk, name)
    return {"status": "saved", "workflow_id": wf.pk, "name": wf.name}


@sync_to_async
def _list_workflows(user_id: str) -> List[Dict[str, Any]]:
    from django.contrib.auth import get_user_model
    from workflows.models import SavedWorkflow

    User = get_user_model()
    user = User.objects.get(supabase_uid=user_id)
    workflows = SavedWorkflow.objects.filter(user=user).values(
        "id", "name", "description", "created_at", "updated_at"
    )
    return [
        {
            "workflow_id": w["id"],
            "name": w["name"],
            "description": w["description"],
            "created_at": w["created_at"].isoformat(),
            "updated_at": w["updated_at"].isoformat(),
        }
        for w in workflows
    ]


async def workflow_save(
    user_id: str,
    name: str,
    plan: dict,
    description: str = "",
    input_schema: Optional[List[dict]] = None,
) -> Dict[str, Any]:
    """Save a plan as a reusable named workflow.

    Args:
        user_id: Supabase UID of the workflow owner.
        name: Human-readable workflow name.
        plan: Complete plan JSON (steps, final_output_var, summary).
        description: Optional description of what the workflow does.
        input_schema: Optional list of input definitions for run-time parameters.

    Returns:
        Save status and the new workflow ID.
    """
    return await _save_workflow(user_id, name, plan, description, input_schema or [])


async def workflow_list(user_id: str) -> List[Dict[str, Any]]:
    """List the user's saved workflows.

    Args:
        user_id: Supabase UID of the workflow owner.

    Returns:
        List of saved workflow summaries.
    """
    return await _list_workflows(user_id)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

register(ToolDef(
    name="workflow.save",
    display_name="Save Workflow",
    description=(
        "Save a plan as a reusable named workflow. Use this when the user asks to save, "
        "create, or name a workflow. The 'plan' param is the complete inner workflow plan "
        "(its own steps/final_output_var/summary). In the inner plan, replace any params "
        "the user would want to vary between runs with '$input.<name>' references, and list "
        "those in 'input_schema' with human-readable labels."
    ),
    params_schema={
        "name": {
            "type": "string",
            "description": "Human-readable workflow name (e.g. 'Morning Email Briefing').",
            "required": True,
            "hint": "input",
        },
        "plan": {
            "type": "object",
            "description": (
                "Complete inner workflow plan JSON with its own steps, final_output_var, and summary. "
                "Params that vary per run should use '$input.<name>' references."
            ),
            "required": True,
        },
        "description": {
            "type": "string",
            "description": "One sentence describing what this workflow does.",
            "required": False,
        },
        "input_schema": {
            "type": "array",
            "description": (
                "List of run-time input definitions. Each entry: "
                "{name, type, label, required?, default?}. "
                "Add one entry for every '$input.<name>' used in the inner plan."
            ),
            "required": False,
        },
    },
    fn=workflow_save,
    requires_user_id=True,
    requires_confirmation=False,
))

register(ToolDef(
    name="workflow.list",
    display_name="List Saved Workflows",
    description="List all of the user's saved workflows by name and ID.",
    params_schema={},
    fn=workflow_list,
    requires_user_id=True,
))
