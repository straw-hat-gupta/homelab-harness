"""REST views for saved workflows.

Endpoints:
  GET  /workflows/            — list all workflows for the authenticated user
  POST /workflows/            — create a workflow
  POST /workflows/validate/   — validate a plan + input_schema without saving
  GET  /workflows/<id>/       — retrieve one workflow
  PUT  /workflows/<id>/       — update name/description/plan/input_schema
  DELETE /workflows/<id>/     — delete
  POST /workflows/<id>/run/   — execute the stored plan (accepts {"inputs": {...}})
"""
from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated

from workflows.models import SavedWorkflow
from backend.pagination import AivaPagination
from workflows.runner import run_saved_workflow
from workflows.scheduling import (
    validate_workflow_plan,
    validate_plan_deep,
    validate_input_schema,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _error(code: str, detail: str) -> dict:
    return {"error": code, "detail": detail}


def _workflow_data(wf: SavedWorkflow) -> dict:
    return {
        "id": wf.pk,
        "name": wf.name,
        "description": wf.description,
        "plan": wf.plan,
        "input_schema": wf.input_schema,
        "project_id": wf.project_id,
        "created_at": wf.created_at.isoformat(),
        "updated_at": wf.updated_at.isoformat(),
    }


def _full_validate(plan_raw, input_schema_raw) -> list[str]:
    """Run Pydantic + registry + variable-ref + input_schema validation.

    Returns a flat list of error strings. Empty list means valid.
    """
    errors: list[str] = []

    # 1. Pydantic structure
    try:
        plan = validate_workflow_plan(plan_raw)
    except Exception as exc:
        return [str(exc)]

    # 2. Tool registry + variable references
    errors.extend(validate_plan_deep(plan))

    # 3. Input schema structure
    if input_schema_raw is not None:
        errors.extend(validate_input_schema(input_schema_raw))

    return errors


# ---------------------------------------------------------------------------
# Collection: list + create
# ---------------------------------------------------------------------------

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def workflow_list_view(request):
    """GET — list all; POST — create a new saved workflow."""

    if request.method == "GET":
        workflows = SavedWorkflow.objects.filter(user=request.user)
        paginator = AivaPagination()
        page = paginator.paginate_queryset(workflows, request)
        return paginator.get_paginated_response([_workflow_data(w) for w in page])

    # POST
    name = request.data.get("name", "").strip()
    if not name:
        return JsonResponse(_error("bad_request", "'name' is required"), status=400)

    plan_raw = request.data.get("plan")
    if plan_raw is None:
        return JsonResponse(_error("bad_request", "'plan' is required"), status=400)

    input_schema_raw = request.data.get("input_schema", [])
    errors = _full_validate(plan_raw, input_schema_raw)
    if errors:
        return JsonResponse({"error": "invalid_plan", "errors": errors}, status=400)

    project_id = request.data.get("project_id")
    if project_id is not None:
        from projects.models import Projects
        if not Projects.objects.filter(pk=project_id, user=request.user).exists():
            return JsonResponse(_error("not_found", "Project not found"), status=404)

    wf = SavedWorkflow.objects.create(
        user=request.user,
        name=name,
        description=request.data.get("description", ""),
        plan=plan_raw,
        input_schema=input_schema_raw,
        project_id=project_id,
    )
    return JsonResponse(_workflow_data(wf), status=201)


# ---------------------------------------------------------------------------
# Validate: dry-run validation without saving
# ---------------------------------------------------------------------------

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def workflow_validate_view(request):
    """Validate a plan + input_schema without saving. Returns structured errors."""
    plan_raw = request.data.get("plan")
    if plan_raw is None:
        return JsonResponse(_error("bad_request", "'plan' is required"), status=400)

    input_schema_raw = request.data.get("input_schema")
    errors = _full_validate(plan_raw, input_schema_raw)
    if errors:
        return JsonResponse({"valid": False, "errors": errors}, status=200)
    return JsonResponse({"valid": True, "errors": []})


# ---------------------------------------------------------------------------
# Detail: retrieve + update + delete
# ---------------------------------------------------------------------------

@api_view(["GET", "PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def workflow_detail_view(request, workflow_id: int):
    """GET/PUT/DELETE on a single workflow owned by the authenticated user."""

    try:
        wf = SavedWorkflow.objects.get(pk=workflow_id, user=request.user)
    except SavedWorkflow.DoesNotExist:
        return JsonResponse(_error("not_found", "Workflow not found"), status=404)

    if request.method == "GET":
        return JsonResponse(_workflow_data(wf))

    if request.method == "DELETE":
        wf.delete()
        return JsonResponse({"status": "ok", "id": workflow_id})

    # PUT — only update fields that are present in the request
    if "name" in request.data:
        name = request.data["name"].strip()
        if not name:
            return JsonResponse(_error("bad_request", "'name' cannot be blank"), status=400)
        wf.name = name

    if "description" in request.data:
        wf.description = request.data["description"]

    new_plan = request.data.get("plan", wf.plan)
    new_input_schema = request.data.get("input_schema", wf.input_schema)

    if "plan" in request.data or "input_schema" in request.data:
        errors = _full_validate(new_plan, new_input_schema)
        if errors:
            return JsonResponse({"error": "invalid_plan", "errors": errors}, status=400)
        wf.plan = new_plan
        wf.input_schema = new_input_schema

    if "project_id" in request.data:
        new_project_id = request.data["project_id"]
        if new_project_id is not None:
            from projects.models import Projects
            if not Projects.objects.filter(pk=new_project_id, user=request.user).exists():
                return JsonResponse(_error("not_found", "Project not found"), status=404)
        wf.project_id = new_project_id

    wf.save()
    return JsonResponse(_workflow_data(wf))


# ---------------------------------------------------------------------------
# Run: execute the stored plan
# ---------------------------------------------------------------------------

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def workflow_run_view(request, workflow_id: int):
    """Execute a saved workflow's plan.

    Accepts an optional {"inputs": {...}} body to satisfy the workflow's
    input_schema. Required inputs that are missing return HTTP 400.
    """
    try:
        wf = SavedWorkflow.objects.select_related("project").get(
            pk=workflow_id, user=request.user
        )
    except SavedWorkflow.DoesNotExist:
        return JsonResponse(_error("not_found", "Workflow not found"), status=404)

    inputs = request.data.get("inputs") if request.data else None

    result = run_saved_workflow(wf, request.user, inputs=inputs or {})

    if result.status == "success":
        return JsonResponse({"result": result.result})

    if result.error_code == "plugin_not_connected":
        return JsonResponse(
            {"error": "plugin_not_connected", "detail": result.error_detail, "plugin": result.plugin_id},
            status=422,
        )

    if result.error_code == "invalid_inputs":
        return JsonResponse(_error("invalid_inputs", result.error_detail or ""), status=400)

    status_code = 500 if result.error_code in {"invalid_plan", "unknown_tool", "execution_error"} else 400
    return JsonResponse(_error(result.error_code or "execution_error", result.error_detail or ""), status=status_code)
