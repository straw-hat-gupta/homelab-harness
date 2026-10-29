import asyncio
import json
import logging
from typing import Optional

from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.throttling import UserRateThrottle

from agent.models import UserMemory
from planner.planner import plan as make_plan, revise_plan, detect_intent
from planner.schemas import Plan
from orchestrator.orchestrator import execute
from orchestrator.exceptions import PluginNotConnectedError, ToolExecutionError
from orchestrator.credentials import get_connected_plugins, get_connected_accounts
from projects.models import Projects
from tools.registry import get as get_tool, get_schemas_for_planner, UnknownToolError
from asgiref.sync import async_to_sync, sync_to_async
from .chat_context import get_ctx
from . import pending_plan as pending_store


class AgentRequestSerializer(serializers.Serializer):
    prompt = serializers.CharField(allow_blank=False, max_length=10_000)
    project_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    dry_run = serializers.BooleanField(default=False)


class AgentThrottle(UserRateThrottle):
    scope = "agent"

    def get_rate(self):
        """Return the configured agent throttle rate.

        Returns:
            DRF throttle rate string.
        """
        return getattr(settings, "AGENT_THROTTLE_RATE", "20/min")

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_enabled_plugins(project: Optional[Projects]) -> Optional[frozenset]:
    """Return frozenset of enabled plugin IDs from project.plugins, or None (= no restriction).

    project.plugins format: {"gmail": true, "google_calendar": false}
    None or empty dict = no restriction, all plugins available.
    """
    if project is None:
        return None
    plugins = project.plugins or {}
    if not plugins:
        return None
    return frozenset(k for k, v in plugins.items() if v)


def _validate_plan_plugins(plan: Plan, enabled_plugins: Optional[frozenset]) -> None:
    """Raise UnknownToolError if the plan uses tools from plugins disabled for this project."""
    if enabled_plugins is None:
        return
    for step in plan.steps:
        tool_def = get_tool(step.tool)
        if tool_def.plugin_id is not None and tool_def.plugin_id not in enabled_plugins:
            raise UnknownToolError(
                f"Tool {step.tool!r} belongs to plugin {tool_def.plugin_id!r} "
                f"which is not enabled for this project."
            )


def _validate_plan_tools(plan: Plan) -> None:
    """Raise UnknownToolError if the plan references a tool not in the registry."""
    for step in plan.steps:
        get_tool(step.tool)


def _needs_confirmation(plan: Plan) -> bool:
    """Check whether a plan includes confirmation-required tools.

    Args:
        plan: Plan to inspect.

    Returns:
        True when any step requires confirmation.
    """
    for step in plan.steps:
        tool_def = get_tool(step.tool)
        if tool_def.requires_confirmation:
            return True
    return False


def _model() -> str:
    """Return the configured planner model name.

    Returns:
        Planner model name.
    """
    return getattr(settings, "PLANNER_MODEL", "gpt-4o-mini")


_MEMORY_INJECT_LIMIT = 20

def _load_user_memories(user) -> list:
    """Return the user's most-recent memories as a list of {key, value} dicts."""
    return list(
        UserMemory.objects.filter(user=user)
        .order_by("-updated_at")[:_MEMORY_INJECT_LIMIT]
        .values("key", "value")
    )


@sync_to_async
def _create_task_record(project, prompt: str, plan: Plan):
    from tasks.models import Task, SubTask
    task = Task.objects.create(
        project=project,
        title=prompt[:255],
        description=plan.summary,
        status=Task.STATUS_RUNNING,
    )
    for i, step in enumerate(plan.steps):
        try:
            tool_def = get_tool(step.tool)
            plugin = tool_def.plugin_id or step.tool
        except Exception:
            plugin = step.tool
        SubTask.objects.create(
            task=task,
            action=step.tool,
            detail="",
            plugin=plugin,
            order=i + 1,
        )
    return task


@sync_to_async
def _finish_task_record(task, status: str) -> None:
    task.status = status
    task.save(update_fields=["status", "updated_at"])


def _error(code: str, message: str, **extra) -> dict:
    """Build a standardized API error payload.

    Args:
        code: Stable error code.
        message: User-facing error message.
        **extra: Additional error fields.

    Returns:
        Error response dictionary.
    """
    return {"error": {"code": code, "message": message, **extra}}


async def _is_stream_throttled(user) -> bool:
    """Sliding-window rate limiter for the async stream endpoint.

    Uses a separate cache key from DRF's sync throttle to avoid format coupling.
    Rate is read from AGENT_THROTTLE_RATE setting (e.g. '20/min').
    """
    import time
    from asgiref.sync import sync_to_async
    from django.core.cache import cache

    rate = getattr(settings, "AGENT_THROTTLE_RATE", "20/min")
    try:
        num_str, period_str = rate.split("/")
        num = int(num_str)
        period_map = {"s": 1, "sec": 1, "min": 60, "hour": 3600, "day": 86400}
        period = period_map[period_str]
    except (ValueError, KeyError):
        num, period = 20, 60

    key = f"throttle_agent_{user.pk}"
    now = time.time()

    timestamps: list = await sync_to_async(cache.get)(key) or []
    timestamps = [t for t in timestamps if now - t < period]

    if len(timestamps) >= num:
        return True

    timestamps.append(now)
    await sync_to_async(cache.set)(key, timestamps, period)
    return False


def _format_completed_steps(completed_steps: list[dict]) -> str:
    """Render completed-step dicts as a plain string for the LLM's inputs."""
    if not completed_steps:
        return "none"
    parts = []
    for s in completed_steps:
        label = s["tool"]
        if s.get("requires_confirmation"):
            label += " (irreversible)"
        parts.append(label)
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Capabilities helpers
# ---------------------------------------------------------------------------

_DEFAULT_CAPABILITIES_PHRASES = frozenset({
    "what can you do", "what can you help with", "what are your capabilities",
    "what tools do you have", "help me understand what you can do",
    "show me what you can do", "list your tools", "list tools",
    "what do you support", "what features do you have",
})


def _capabilities_phrases() -> frozenset:
    """Return phrases that trigger the capabilities shortcut.

    Returns:
        Set of normalized trigger phrases.
    """
    phrases = getattr(settings, "CAPABILITIES_PHRASES", None)
    if phrases:
        return frozenset(p.lower() for p in phrases)
    return _DEFAULT_CAPABILITIES_PHRASES


def _is_capabilities_query(prompt: str) -> bool:
    """Determine whether a prompt asks about available capabilities.

    Args:
        prompt: User prompt.

    Returns:
        True when the capabilities shortcut should run.
    """
    normalized = prompt.strip().lower().rstrip("?.")
    return any(normalized == phrase or normalized.startswith(phrase) for phrase in _capabilities_phrases())


def _capabilities_response(tool_schemas: list, connected_plugins: list) -> str:
    """Render a capabilities response from visible tools.

    Args:
        tool_schemas: Planner-visible tool schemas.
        connected_plugins: Plugin IDs with active credentials.

    Returns:
        User-facing capabilities summary.
    """
    # tool_schemas is already filtered by enabled_plugins — iterate it, not _REGISTRY.
    groups: dict[str, list[str]] = {}
    for schema in tool_schemas:
        name = schema["name"]
        prefix = name.split(".")[0] if "." in name else name
        groups.setdefault(prefix, []).append(f"  • **{name}** — {schema['description']}")

    lines = ["Here's what I can help you with:\n"]
    for group, items in sorted(groups.items()):
        connected = group in connected_plugins or group == "processing_llm"
        status = "" if connected or group in ("processing_llm", "weather", "contacts") else " *(not connected)*"
        lines.append(f"**{group.replace('_', ' ').title()}**{status}")
        lines.extend(items)
        lines.append("")

    if not connected_plugins:
        lines.append("*Tip: Connect plugins in **Settings → Plugins** to unlock Gmail, Google Calendar, and more.*")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core async logic
# ---------------------------------------------------------------------------

async def run_prompt(
    prompt: str,
    user_id: str,
    project_id: str | None = None,
    dry_run: bool = False,
    enabled_plugins: Optional[frozenset] = None,
    on_step=None,  # async callable(step_id, tool, index, total) -> None
    memories: Optional[list] = None,
    project=None,  # Projects instance for task recording; None = no project context
) -> str:
    """Plan and execute one agent prompt.

    Args:
        prompt: User prompt.
        user_id: Supabase UID of the requester.
        project_id: Optional project identifier.
        dry_run: Whether confirmation-required steps should be previewed only.
        enabled_plugins: Optional project-enabled plugin set.
        on_step: Optional async callback invoked after each completed step.

    Returns:
        User-facing response string.
    """
    user_id_str = str(user_id) if user_id else "anonymous"
    project_id_str = str(project_id) if project_id is not None else "default"

    logger.info(
        "run_prompt start user_id=%s project_id=%s prompt_len=%d dry_run=%s",
        user_id_str,
        project_id_str,
        len(prompt),
        dry_run,
    )

    ctx = get_ctx(user_id_str, project_id_str)
    tool_schemas = get_schemas_for_planner(enabled_plugins=enabled_plugins)
    connected_accounts = await get_connected_accounts(user_id_str)
    if enabled_plugins is not None:
        connected_accounts = [a for a in connected_accounts if a["plugin"] in enabled_plugins]
    connected_plugins = list({a["plugin"] for a in connected_accounts})
    pending = pending_store.load(user_id_str, project_id_str)

    # ------------------------------------------------------------------
    # Capabilities shortcut — answer without calling the planner/LLM
    # ------------------------------------------------------------------
    if pending is None and _is_capabilities_query(prompt):
        reply = _capabilities_response(tool_schemas, connected_plugins)
        ctx.add_user(prompt)
        ctx.add_assistant(reply)
        return reply

    # ------------------------------------------------------------------
    # Branch A: a plan is waiting for confirmation
    # ------------------------------------------------------------------
    if pending is not None:
        logger.info(
            "run_prompt pending plan found user_id=%s project_id=%s steps=%d",
            user_id_str,
            project_id_str,
            len(pending.steps),
        )
        intent = await detect_intent(prompt, pending.summary, model=_model(), user_id=user_id_str)
        logger.info(
            "run_prompt pending intent=%s user_id=%s project_id=%s",
            intent,
            user_id_str,
            project_id_str,
        )

        if intent == "confirm":
            logger.info(
                "run_prompt executing confirmed plan user_id=%s project_id=%s",
                user_id_str,
                project_id_str,
            )
            _validate_plan_plugins(pending, enabled_plugins)
            pending_store.clear(user_id_str, project_id_str)
            pending_store.reset_modify_count(user_id_str, project_id_str)
            task_record = None
            if project is not None:
                task_record = await _create_task_record(project, prompt, pending)
            try:
                result = await execute(pending, user_id=user_id_str, on_step=on_step)
                if task_record is not None:
                    await _finish_task_record(task_record, "completed")
            except Exception:
                if task_record is not None:
                    await _finish_task_record(task_record, "failed")
                raise
            ctx.add_user(prompt)
            ctx.add_assistant(result)
            logger.info(
                "run_prompt confirmed plan complete user_id=%s project_id=%s response_len=%d",
                user_id_str,
                project_id_str,
                len(result),
            )
            return result

        if intent == "cancel":
            pending_store.clear(user_id_str, project_id_str)
            pending_store.reset_modify_count(user_id_str, project_id_str)
            reply = "Got it — cancelled. What else can I help you with?"
            ctx.add_user(prompt)
            ctx.add_assistant(reply)
            logger.info(
                "run_prompt pending plan cancelled user_id=%s project_id=%s",
                user_id_str,
                project_id_str,
            )
            return reply

        # "modify" — revise the plan with the user's feedback, then re-confirm
        max_revisions = getattr(settings, "AGENT_MAX_MODIFY_REVISIONS", 5)
        modify_count = pending_store.get_modify_count(user_id_str, project_id_str)
        if modify_count >= max_revisions:
            pending_store.clear(user_id_str, project_id_str)
            pending_store.reset_modify_count(user_id_str, project_id_str)
            reply = (
                "I've revised this plan several times and we seem to be going in circles. "
                "Please start a fresh request describing exactly what you'd like to do."
            )
            ctx.add_user(prompt)
            ctx.add_assistant(reply)
            logger.info(
                "run_prompt modify cap hit user_id=%s project_id=%s modify_count=%d",
                user_id_str,
                project_id_str,
                modify_count,
            )
            return reply

        logger.info(
            "run_prompt revising pending plan user_id=%s project_id=%s modify_count=%d",
            user_id_str,
            project_id_str,
            modify_count,
        )
        new_plan = await revise_plan(
            current_plan=pending,
            feedback=prompt,
            history=ctx.as_messages(),
            tool_schemas=tool_schemas,
            model=_model(),
            connected_accounts=connected_accounts,
            user_id=user_id_str,
            memories=memories,
        )
        logger.debug("Revised plan: %s", new_plan.model_dump_json(indent=2))
        logger.info(
            "run_prompt revised pending plan user_id=%s project_id=%s steps=%d tools=%s",
            user_id_str,
            project_id_str,
            len(new_plan.steps),
            [step.tool for step in new_plan.steps],
        )

        _validate_plan_tools(new_plan)
        _validate_plan_plugins(new_plan, enabled_plugins)
        pending_store.save(user_id_str, project_id_str, new_plan)
        pending_store.increment_modify_count(user_id_str, project_id_str)
        reply = f"{new_plan.summary}\n\nShall I proceed?"
        ctx.add_user(prompt)
        ctx.add_assistant(reply)
        return reply

    # ------------------------------------------------------------------
    # Branch B: fresh request — build a new plan
    # ------------------------------------------------------------------
    logger.info(
        "run_prompt planning start user_id=%s project_id=%s history_messages=%d tool_count=%d",
        user_id_str,
        project_id_str,
        len(ctx.as_messages()),
        len(tool_schemas),
    )
    new_plan = await make_plan(
        prompt=prompt,
        history=ctx.as_messages(),
        tool_schemas=tool_schemas,
        model=_model(),
        connected_accounts=connected_accounts,
        memories=memories,
    )
    logger.debug("Plan: %s", new_plan.model_dump_json(indent=2))
    logger.info(
        "run_prompt planning complete user_id=%s project_id=%s steps=%d tools=%s",
        user_id_str,
        project_id_str,
        len(new_plan.steps),
        [step.tool for step in new_plan.steps],
    )

    _validate_plan_tools(new_plan)
    _validate_plan_plugins(new_plan, enabled_plugins)

    if _needs_confirmation(new_plan) and not dry_run:
        logger.info(
            "run_prompt confirmation required user_id=%s project_id=%s",
            user_id_str,
            project_id_str,
        )
        pending_store.save(user_id_str, project_id_str, new_plan)
        reply = f"{new_plan.summary}\n\nShall I proceed?"
        ctx.add_user(prompt)
        ctx.add_assistant(reply)
        return reply

    # No confirmation needed (or dry_run bypasses confirmation) — execute immediately
    logger.info(
        "run_prompt executing immediate plan user_id=%s project_id=%s dry_run=%s",
        user_id_str,
        project_id_str,
        dry_run,
    )
    task_record = None
    if project is not None and not dry_run:
        task_record = await _create_task_record(project, prompt, new_plan)
    try:
        result = await execute(new_plan, user_id=user_id_str, dry_run=dry_run, on_step=on_step)
        if task_record is not None:
            await _finish_task_record(task_record, "completed")
    except Exception:
        if task_record is not None:
            await _finish_task_record(task_record, "failed")
        raise
    ctx.add_user(prompt)
    ctx.add_assistant(result)
    logger.info(
        "run_prompt immediate plan complete user_id=%s project_id=%s response_len=%d",
        user_id_str,
        project_id_str,
        len(result),
    )
    return result


# ---------------------------------------------------------------------------
# Django view
# ---------------------------------------------------------------------------

@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([AgentThrottle])
def agent_view(request):
    """Handle the synchronous agent endpoint.

    Args:
        request: Authenticated DRF request with prompt payload.

    Returns:
        JSON response containing the agent response or an error payload.
    """
    # Validate input — outside the execution try/except so ParseError and Http404 propagate normally.
    serializer = AgentRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return JsonResponse(_error("bad_request", "Invalid request."), status=400)

    prompt = serializer.validated_data["prompt"]
    project_id = serializer.validated_data.get("project_id")
    dry_run = serializer.validated_data["dry_run"]
    user_id = request.user.supabase_uid

    project = None
    if project_id is not None:
        project = get_object_or_404(Projects, pk=project_id, user=request.user)

    enabled_plugins = _get_enabled_plugins(project)
    project_id_str = str(project_id) if project_id is not None else "default"
    memories = _load_user_memories(request.user)

    logger.info(
        "agent_view request received user_id=%s project_id=%s prompt_len=%d dry_run=%s",
        user_id,
        project_id_str,
        len(prompt),
        dry_run,
    )

    try:
        result = async_to_sync(run_prompt)(
            prompt, user_id, project_id_str, dry_run=dry_run, enabled_plugins=enabled_plugins,
            memories=memories, project=project,
        )
        logger.info(
            "agent_view request complete user_id=%s project_id=%s response_len=%d dry_run=%s",
            user_id,
            project_id_str,
            len(result),
            dry_run,
        )
        response_body: dict = {"response": result}
        if dry_run:
            response_body["dry_run"] = True
        return JsonResponse(response_body)

    except PluginNotConnectedError as exc:
        return JsonResponse(
            _error("plugin_not_connected", str(exc), plugin=exc.plugin_id),
            status=422,
        )

    except ToolExecutionError as exc:
        logger.error(
            "Tool execution error in agent_view step=%s tool=%s: %s",
            exc.step_id, exc.tool, exc,
        )
        from tools.processing_llm.tool import call_processing_llm
        completed_summary = _format_completed_steps(exc.completed_steps)
        try:
            friendly_msg = async_to_sync(call_processing_llm)(
                task=(
                    "Explain what went wrong to the user in plain, friendly language (1-2 sentences). "
                    "If 'completed_steps' lists any steps that ran before the failure, briefly mention what was accomplished — "
                    "and if any step is marked requires_confirmation=true, warn the user it was irreversible (e.g. an email was sent). "
                    "If it looks like an auth or permission error (403, scope, token expired, revoked), "
                    "tell them to reconnect the plugin in Settings. "
                    "If it's a temporary network or server error, suggest trying again. "
                    "Do not mention HTTP status codes, stack traces, or internal details."
                ),
                inputs={"error": str(exc), "tool": exc.tool, "completed_steps": completed_summary},
            )
        except Exception:
            friendly_msg = f"Something went wrong while running '{exc.tool}'. Please try again."
        body = _error("tool_execution_failed", friendly_msg)
        if exc.completed_steps:
            body["error"]["completed_steps"] = exc.completed_steps
        return JsonResponse(body, status=500)

    except UnknownToolError as exc:
        logger.error("Plan references unknown tool: %s", exc)
        return JsonResponse(
            _error("unknown_tool", "The plan references a tool that is not available."),
            status=400,
        )

    except Exception:
        logger.exception("Unhandled error in agent_view")
        return JsonResponse(
            _error("internal_error", "An unexpected error occurred. Please try again."),
            status=500,
        )


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def actions_view(request):
    """Return recent confirmed-action audit records for the current user.

    Args:
        request: Authenticated DRF request with optional filters.
    Optional query parameters:
        ?limit=N      Max records (default 50, cap 200).
        ?tool=name    Filter by exact tool name (e.g. gmail.send_email).
        ?status=s     Filter by status (success | failed).
        ?since=ISO    Only records at or after this ISO 8601 datetime.

    Returns:
        JSON response containing audit log records.
    """
    from datetime import datetime, timezone
    from .models import AgentAction

    try:
        limit = min(int(request.query_params.get("limit", 50)), 200)
    except (TypeError, ValueError):
        limit = 50

    qs = AgentAction.objects.filter(user=request.user)

    tool_filter = request.query_params.get("tool")
    if tool_filter:
        qs = qs.filter(tool=tool_filter)

    status_filter = request.query_params.get("status")
    if status_filter:
        qs = qs.filter(status=status_filter)

    since_raw = request.query_params.get("since")
    if since_raw:
        try:
            since_dt = datetime.fromisoformat(since_raw)
            if since_dt.tzinfo is None:
                since_dt = since_dt.replace(tzinfo=timezone.utc)
            qs = qs.filter(timestamp__gte=since_dt)
        except ValueError:
            return JsonResponse(
                _error("bad_request", "'since' must be a valid ISO 8601 datetime."),
                status=400,
            )

    qs = qs.order_by("-timestamp")[:limit]
    data = [
        {
            "id": a.id,
            "tool": a.tool,
            "params_summary": a.params_summary,
            "status": a.status,
            "timestamp": a.timestamp.isoformat(),
        }
        for a in qs
    ]
    return JsonResponse({"actions": data})


# ---------------------------------------------------------------------------
# Conversation reset
# ---------------------------------------------------------------------------

@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def reset_view(request, project_id: int):
    """Clear conversation history and pending plan for a project.

    Args:
        request: Authenticated DRF request.
        project_id: Project primary key.

    Returns:
        JSON response confirming reset.
    """
    from context.models import ProjectContext

    project = get_object_or_404(Projects, pk=project_id, user=request.user)
    ProjectContext.objects.filter(project=project).delete()
    project.pending_plan = None
    project.active_context_from = 0
    project.save(update_fields=["pending_plan", "active_context_from", "updated_at"])
    logger.info(
        "reset_view cleared context user_id=%s project_id=%s",
        request.user.supabase_uid,
        project_id,
    )
    return JsonResponse({"status": "ok", "project_id": project_id})


# ---------------------------------------------------------------------------
# SSE streaming helpers
# ---------------------------------------------------------------------------

def _sse(event: str, data: dict) -> bytes:
    """Serialize one server-sent event.

    Args:
        event: SSE event name.
        data: JSON-serializable event payload.

    Returns:
        Encoded SSE frame.
    """
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


async def _auth_stream(request):
    """Authenticate a request for the async stream endpoint.

    Args:
        request: Incoming Django request.

    Returns:
        Tuple of `(user, None)` or `(None, error_message)`.
    """
    from authentication.authentication import SupabaseAuthentication
    from rest_framework.exceptions import AuthenticationFailed
    from asgiref.sync import sync_to_async
    auth = SupabaseAuthentication()
    try:
        result = await sync_to_async(auth.authenticate)(request)
    except AuthenticationFailed as exc:
        return None, str(exc)
    if result is None:
        return None, "Authentication required"
    return result[0], None


# ---------------------------------------------------------------------------
# Streaming SSE endpoint  POST /agent/stream/
# ---------------------------------------------------------------------------

@csrf_exempt
async def agent_stream_view(request):
    """Streaming variant of agent_view that emits SSE events as each plan step completes.

    Events:
        status  {"message": str}                         — planning started
        step    {"step_id", "tool", "index", "total"}    — each step completed
        done    {"response": str, "dry_run": bool}        — final answer
        error   {"code": str, "message": str, ...}        — any error

    Args:
        request: Authenticated request with prompt payload.

    Returns:
        Streaming HTTP response with SSE events or JSON error response.
    """
    if request.method != "POST":
        return JsonResponse(_error("method_not_allowed", "Use POST."), status=405)

    user, auth_error = await _auth_stream(request)
    if user is None:
        return JsonResponse(_error("unauthorized", auth_error or "Authentication required"), status=401)

    if await _is_stream_throttled(user):
        return JsonResponse(_error("throttled", "Too many requests. Please wait and try again."), status=429)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse(_error("bad_request", "Invalid JSON body."), status=400)

    serializer = AgentRequestSerializer(data=body)
    if not serializer.is_valid():
        return JsonResponse(_error("bad_request", "Invalid request."), status=400)

    prompt = serializer.validated_data["prompt"]
    project_id = serializer.validated_data.get("project_id")
    dry_run = serializer.validated_data["dry_run"]
    user_id = user.supabase_uid

    project = None
    if project_id is not None:
        from asgiref.sync import sync_to_async
        try:
            project = await sync_to_async(Projects.objects.get)(pk=project_id, user=user)
        except Projects.DoesNotExist:
            return JsonResponse(_error("not_found", "Project not found."), status=404)

    enabled_plugins = _get_enabled_plugins(project)
    project_id_str = str(project_id) if project_id is not None else "default"
    from asgiref.sync import sync_to_async
    memories = await sync_to_async(_load_user_memories)(user)

    logger.info(
        "agent_stream_view request user_id=%s project_id=%s prompt_len=%d dry_run=%s",
        user_id, project_id_str, len(prompt), dry_run,
    )

    # All asyncio objects live inside event_generator so they are bound to whichever
    # event loop iterates the generator (ASGI handler in prod, test runner in tests).
    async def event_generator():
        """Generate SSE events for one agent stream request.

        Returns:
            Async iterator yielding encoded SSE frames.
        """
        queue: asyncio.Queue = asyncio.Queue()

        async def on_step(step_id: str, tool: str, index: int, total: int) -> None:
            """Queue a completed-step SSE event.

            Args:
                step_id: Plan step identifier.
                tool: Tool name that completed.
                index: Zero-based completed-step index.
                total: Total number of plan steps.

            Returns:
                None.
            """
            await queue.put(("step", {"step_id": step_id, "tool": tool, "index": index, "total": total}))

        async def run_and_push() -> None:
            """Execute the agent request and queue stream events.

            Returns:
                None.
            """
            try:
                await queue.put(("status", {"message": "Planning..."}))
                result = await run_prompt(
                    prompt, user_id, project_id_str,
                    dry_run=dry_run, enabled_plugins=enabled_plugins,
                    on_step=on_step, memories=memories, project=project,
                )
                await queue.put(("done", {"response": result, "dry_run": dry_run}))
            except PluginNotConnectedError as exc:
                await queue.put(("error", _error("plugin_not_connected", str(exc), plugin=exc.plugin_id)["error"]))
            except ToolExecutionError as exc:
                logger.error("Tool error in agent_stream_view step=%s tool=%s: %s", exc.step_id, exc.tool, exc)
                from tools.processing_llm.tool import call_processing_llm
                completed_summary = _format_completed_steps(exc.completed_steps)
                try:
                    friendly_msg = await call_processing_llm(
                        task=(
                            "Explain what went wrong to the user in plain, friendly language (1-2 sentences). "
                            "If 'completed_steps' lists any steps that ran before the failure, briefly mention what was accomplished — "
                            "and if any step is marked requires_confirmation=true, warn the user it was irreversible (e.g. an email was sent). "
                            "If it looks like an auth or permission error (403, scope, token expired, revoked), "
                            "tell them to reconnect the plugin in Settings. "
                            "If it's a temporary network or server error, suggest trying again. "
                            "Do not mention HTTP status codes, stack traces, or internal details."
                        ),
                        inputs={"error": str(exc), "tool": exc.tool, "completed_steps": completed_summary},
                    )
                except Exception:
                    friendly_msg = f"Something went wrong while running '{exc.tool}'. Please try again."
                err = _error("tool_execution_failed", friendly_msg)["error"]
                if exc.completed_steps:
                    err["completed_steps"] = exc.completed_steps
                await queue.put(("error", err))
            except UnknownToolError as exc:
                logger.error("Unknown tool in agent_stream_view: %s", exc)
                await queue.put(("error", _error("unknown_tool", "The plan references a tool that is not available.")["error"]))
            except Exception:
                logger.exception("Unhandled error in agent_stream_view")
                await queue.put(("error", _error("internal_error", "An unexpected error occurred. Please try again.")["error"]))
            finally:
                await queue.put(None)

        task = asyncio.ensure_future(run_and_push())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                kind, data = item
                yield _sse(kind, data)
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    return StreamingHttpResponse(
        event_generator(),
        content_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Memory CRUD
# ---------------------------------------------------------------------------

class MemorySerializer(serializers.Serializer):
    key = serializers.CharField(max_length=255)
    value = serializers.CharField()


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def memory_list_view(request):
    """List or create user memories.

    GET  /agent/memory/ — list all memories for the authenticated user.
    POST /agent/memory/ — upsert a memory by key (create or update).

    Returns:
        JSON response containing memories list or created/updated memory.
    """
    if request.method == "GET":
        memories = UserMemory.objects.filter(user=request.user)
        data = [
            {
                "id": m.id,
                "key": m.key,
                "value": m.value,
                "source": m.source,
                "created_at": m.created_at.isoformat(),
                "updated_at": m.updated_at.isoformat(),
            }
            for m in memories
        ]
        return JsonResponse({"memories": data})

    serializer = MemorySerializer(data=request.data)
    if not serializer.is_valid():
        return JsonResponse(_error("bad_request", "Invalid request."), status=400)

    key = serializer.validated_data["key"]
    value = serializer.validated_data["value"]
    obj, created = UserMemory.objects.update_or_create(
        user=request.user,
        key=key,
        defaults={"value": value, "source": UserMemory.SOURCE_MANUAL},
    )
    return JsonResponse(
        {
            "id": obj.id,
            "key": obj.key,
            "value": obj.value,
            "source": obj.source,
            "created_at": obj.created_at.isoformat(),
            "updated_at": obj.updated_at.isoformat(),
        },
        status=201 if created else 200,
    )


@api_view(["PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def memory_detail_view(request, memory_id: int):
    """Update or delete a specific memory.

    PUT    /agent/memory/<id>/ — update value for an existing memory.
    DELETE /agent/memory/<id>/ — delete a memory.

    Returns:
        JSON response with updated memory or deletion confirmation.
    """
    memory = get_object_or_404(UserMemory, pk=memory_id, user=request.user)

    if request.method == "DELETE":
        memory.delete()
        return JsonResponse({"status": "ok", "id": memory_id})

    serializer = MemorySerializer(data=request.data)
    if not serializer.is_valid():
        return JsonResponse(_error("bad_request", "Invalid request."), status=400)

    memory.key = serializer.validated_data["key"]
    memory.value = serializer.validated_data["value"]
    memory.source = UserMemory.SOURCE_MANUAL
    memory.save(update_fields=["key", "value", "source", "updated_at"])
    return JsonResponse(
        {
            "id": memory.id,
            "key": memory.key,
            "value": memory.value,
            "source": memory.source,
            "created_at": memory.created_at.isoformat(),
            "updated_at": memory.updated_at.isoformat(),
        }
    )
