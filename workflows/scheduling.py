from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from pydantic import ValidationError as PydanticValidationError

from planner.schemas import Plan
from tools.registry import UnknownToolError, get as get_tool
from workflows.models import SavedWorkflow, compute_next_run_at, validate_cron_expression, validate_timezone_name

_VALID_INPUT_TYPES = {"string", "integer", "number", "boolean", "array", "object"}


@dataclass
class WorkflowScheduleValidationError(Exception):
    code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


def validate_schedule_fields(cron: str, timezone_name: str) -> None:
    """Validate schedule fields before model creation/update."""
    try:
        validate_cron_expression(cron)
        validate_timezone_name(timezone_name)
    except DjangoValidationError as exc:
        detail = "; ".join(str(message) for message in exc.messages)
        raise WorkflowScheduleValidationError("invalid_schedule", detail)


def validate_workflow_plan(raw_plan: Any) -> Plan:
    """Validate a saved workflow plan JSON value."""
    if not isinstance(raw_plan, dict):
        raise WorkflowScheduleValidationError("invalid_plan", "workflow plan must be a JSON object")
    try:
        return Plan.model_validate(raw_plan)
    except PydanticValidationError as exc:
        raise WorkflowScheduleValidationError("invalid_plan", str(exc))


def validate_workflow_schedulable(workflow: SavedWorkflow) -> Plan:
    """Return a validated plan or raise if the workflow cannot be scheduled."""
    if workflow.project_id and workflow.project.user_id != workflow.user_id:
        raise WorkflowScheduleValidationError(
            "invalid_workflow",
            "workflow project must belong to the same user as the workflow",
        )

    plan = validate_workflow_plan(workflow.plan)
    for step in plan.steps:
        try:
            get_tool(step.tool)
        except UnknownToolError as exc:
            raise WorkflowScheduleValidationError("unknown_tool", str(exc))
    return plan


def build_workflow_initial_context(workflow: SavedWorkflow, inputs: dict | None = None) -> dict:
    """Build the initial orchestrator context used by saved workflow execution."""
    initial_context = {}
    if workflow.project and workflow.project.system_prompt:
        initial_context["project_system_prompt"] = workflow.project.system_prompt
    if inputs:
        initial_context["input"] = inputs
    return initial_context


def next_run_for_schedule(cron: str, timezone_name: str, from_time=None):
    validate_schedule_fields(cron, timezone_name)
    return compute_next_run_at(cron, timezone_name, from_time=from_time)


# ---------------------------------------------------------------------------
# Input schema validation
# ---------------------------------------------------------------------------

def validate_input_schema(raw: Any) -> list[str]:
    """Return a list of error strings for an invalid input_schema value."""
    if not isinstance(raw, list):
        return ["input_schema must be a JSON array"]
    errors = []
    seen_names: set[str] = set()
    for i, entry in enumerate(raw):
        prefix = f"input_schema[{i}]"
        if not isinstance(entry, dict):
            errors.append(f"{prefix}: each entry must be a JSON object")
            continue
        name = entry.get("name")
        if not name or not isinstance(name, str):
            errors.append(f"{prefix}: 'name' is required and must be a string")
        elif not name.isidentifier():
            errors.append(f"{prefix}: 'name' must be a valid identifier (no spaces or dots)")
        elif name in seen_names:
            errors.append(f"{prefix}: duplicate input name '{name}'")
        else:
            seen_names.add(name)
        typ = entry.get("type")
        if not typ:
            errors.append(f"{prefix}: 'type' is required")
        elif typ not in _VALID_INPUT_TYPES:
            errors.append(f"{prefix}: 'type' must be one of {sorted(_VALID_INPUT_TYPES)}")
    return errors


# ---------------------------------------------------------------------------
# Plan deep validation (tool registry + variable references)
# ---------------------------------------------------------------------------

def _collect_refs(value: Any) -> list[str]:
    """Collect all $var_name references from a param value tree."""
    refs: list[str] = []
    if isinstance(value, str) and value.startswith("$"):
        refs.append(value[1:])
    elif isinstance(value, dict):
        for v in value.values():
            refs.extend(_collect_refs(v))
    elif isinstance(value, list):
        for item in value:
            refs.extend(_collect_refs(item))
    return refs


def validate_plan_deep(plan: Plan) -> list[str]:
    """Validate tool names and variable references in a plan.

    Returns a list of human-readable error strings (empty = valid).
    """
    errors: list[str] = []
    known_vars: set[str] = set()

    for step in plan.steps:
        try:
            get_tool(step.tool)
        except UnknownToolError:
            errors.append(f"Step '{step.id}': unknown tool '{step.tool}'")

        for param_key, param_val in step.params.items():
            for ref in _collect_refs(param_val):
                if ref.startswith("input."):
                    continue  # $input.* is resolved at run time from workflow inputs
                if ref not in known_vars:
                    errors.append(
                        f"Step '{step.id}' param '{param_key}': "
                        f"references undefined variable '${ref}'"
                    )

        known_vars.add(step.output_var)

    if plan.final_output_var not in known_vars:
        errors.append(
            f"final_output_var '${plan.final_output_var}' is not produced by any step"
        )

    return errors


# ---------------------------------------------------------------------------
# Input resolution at run time
# ---------------------------------------------------------------------------

def resolve_and_validate_inputs(
    input_schema: list[dict],
    provided: dict,
) -> tuple[dict, list[str]]:
    """Validate provided inputs against the schema and apply defaults.

    Returns (resolved_inputs, errors). errors is empty on success.
    """
    errors: list[str] = []
    resolved: dict = {}

    for entry in input_schema:
        name = entry.get("name", "")
        required = entry.get("required", False)
        default = entry.get("default")
        expected_type = entry.get("type", "string")

        if name in provided:
            value = _coerce_input(provided[name], expected_type)
            resolved[name] = value
        elif default is not None:
            resolved[name] = default
        elif required:
            errors.append(f"Missing required input '{name}'")

    return resolved, errors


def _coerce_input(value: Any, expected_type: str) -> Any:
    try:
        if expected_type == "integer":
            return int(value)
        if expected_type == "number":
            return float(value)
        if expected_type == "boolean":
            if isinstance(value, bool):
                return value
            return str(value).lower() in ("true", "1", "yes")
        if expected_type == "array" and isinstance(value, str):
            return [value]
    except (TypeError, ValueError):
        pass
    return value
