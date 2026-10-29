import asyncio
import json
import logging
from typing import Any, Dict, Optional

import requests

from asgiref.sync import sync_to_async

from planner.schemas import Plan
from tools.registry import get as get_tool, UnknownToolError
from orchestrator.credentials import load_credentials, save_credentials
from orchestrator.exceptions import PluginNotConnectedError, ToolExecutionError


@sync_to_async
def _record_action(user_id: str, tool: str, params_summary: str, status: str) -> None:
    """Persist an audit record for an agent tool action.

    Args:
        user_id: Supabase UID of the acting user.
        tool: Tool name that was executed.
        params_summary: Redacted parameter summary.
        status: Action status value.

    Returns:
        None.
    """
    from django.contrib.auth import get_user_model
    from agent.models import AgentAction
    User = get_user_model()
    try:
        user = User.objects.get(supabase_uid=user_id)
        AgentAction.objects.create(
            user=user,
            tool=tool,
            params_summary=params_summary,
            status=status,
        )
    except Exception:
        logger.warning("Failed to record agent action for user=%s tool=%s", user_id, tool, exc_info=True)

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
_BASE_DELAY = 1.0  # seconds; doubles each retry (1s, 2s, 4s)


def _is_retryable(exc: Exception) -> bool:
    """Decide whether a tool exception should be retried.

    Args:
        exc: Exception raised by a tool call.

    Returns:
        True for transient network/server errors (5xx, 429, connection failures).
    """
    if isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
        return True
    if isinstance(exc, requests.exceptions.HTTPError):
        if exc.response is not None:
            status = exc.response.status_code
            return status >= 500 or status == 429
        return False
    # Google API errors
    try:
        from googleapiclient.errors import HttpError
        if isinstance(exc, HttpError):
            status = int(exc.resp.status)
            return status >= 500 or status == 429
    except ImportError:
        pass
    return False


def _resolve(value: Any, context: Dict[str, Any]) -> Any:
    """Resolve plan variable references against step outputs.

    Supports:
      $var_name        — top-level context key (prior step output)
      $input.name      — one-level dot notation into context["input"] dict

    Args:
        value: Parameter value, list, or dictionary to resolve.
        context: Execution context keyed by prior step output variables.

    Returns:
        Value with `$variable` references replaced.
    """
    if isinstance(value, str) and value.startswith("$"):
        var_name = value[1:]
        if "." in var_name:
            root_key, sub_key = var_name.split(".", 1)
            root = context.get(root_key)
            if not isinstance(root, dict) or sub_key not in root:
                raise KeyError(f"Plan references undefined variable: ${var_name!r}")
            return root[sub_key]
        if var_name not in context:
            raise KeyError(f"Plan references undefined variable: ${var_name!r}")
        return context[var_name]
    if isinstance(value, dict):
        return {k: _resolve(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(item, context) for item in value]
    return value


async def _call_with_retry(tool_name: str, fn, **kwargs) -> Any:
    """Call a tool function with retry handling for transient errors.

    Args:
        tool_name: Registered tool name for logging.
        fn: Async tool callable.
        **kwargs: Tool keyword arguments.

    Returns:
        Tool result.
    """
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            return await fn(**kwargs)
        except Exception as exc:
            if not _is_retryable(exc):
                raise
            last_exc = exc
            if attempt < MAX_RETRIES:
                delay = _BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "Tool %r attempt %d/%d failed with server error — retrying in %.1fs: %s",
                    tool_name,
                    attempt + 1,
                    MAX_RETRIES,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
    raise last_exc  # type: ignore[misc]


async def execute(
    plan: Plan,
    user_id: str,
    dry_run: bool = False,
    on_step=None,
    initial_context: Optional[Dict[str, Any]] = None,
) -> str:
    """Execute a planner-produced plan sequentially.

    For each step:
    1. Resolve any '$var' references in params from the execution context.
    2. Inject credentials (token_data) for tools that require them.
    3. Call the tool, retrying on server errors (5xx) up to MAX_RETRIES times.
    4. Persist any refreshed credentials returned in 'updated_token_data'.
    5. Store the result in the execution context under output_var.

    When dry_run=True, steps with requires_confirmation=True are skipped and a
    placeholder is stored instead, so the final processing_llm step can explain
    what would have happened.

    Args:
        plan: Validated execution plan.
        user_id: Supabase UID of the user executing the plan.
        dry_run: Whether confirmation-required steps should be previewed only.
        on_step: Optional async callback invoked after each completed step.
        initial_context: Optional pre-seeded variables available to all steps
            via $variable references (e.g. {"project_system_prompt": "..."}).

    Returns:
        Final user-facing response string.
    """
    context: Dict[str, Any] = dict(initial_context) if initial_context else {}
    completed: list[dict] = []
    dry_run_skipped: list[str] = []
    logger.info(
        "execute start user_id=%s steps=%d tools=%s dry_run=%s",
        user_id,
        len(plan.steps),
        [step.tool for step in plan.steps],
        dry_run,
    )

    for step in plan.steps:
        try:
            tool_def = get_tool(step.tool)
        except UnknownToolError as e:
            logger.error("Step %s: %s", step.id, e)
            raise ToolExecutionError(step.id, step.tool, str(e), completed)

        try:
            resolved_params = _resolve(step.params, context)
        except KeyError as e:
            logger.error("Step %s references an undefined variable: %s", step.id, e)
            raise ToolExecutionError(step.id, step.tool, f"references undefined variable {e}", completed)

        logger.info(
            "execute step start user_id=%s step_id=%s tool=%s requires_creds=%s",
            user_id,
            step.id,
            step.tool,
            tool_def.requires_creds,
        )

        # Inject credentials for plugins that need them
        if tool_def.requires_creds:
            logger.info(
                "execute step loading credentials user_id=%s step_id=%s plugin_id=%s",
                user_id,
                step.id,
                tool_def.plugin_id,
            )
            try:
                creds = await load_credentials(user_id, tool_def.plugin_id, step.account_id)
            except Exception as e:
                from django.db import models as _dj_models
                from plugins.models import Credentials
                if isinstance(e, Credentials.DoesNotExist):
                    raise PluginNotConnectedError(tool_def.plugin_id) from e
                raise ToolExecutionError(step.id, step.tool, str(e), completed) from e
            resolved_params["token_data"] = creds
            logger.info(
                "execute step credentials loaded user_id=%s step_id=%s plugin_id=%s",
                user_id,
                step.id,
                tool_def.plugin_id,
            )

        if tool_def.requires_user_id:
            resolved_params["user_id"] = user_id

        # Dry-run: skip confirmation-required steps and store a preview placeholder.
        if dry_run and tool_def.requires_confirmation:
            safe_params = {k: v for k, v in resolved_params.items() if k != "token_data"}
            context[step.output_var] = {
                "dry_run": True,
                "tool": step.tool,
                "params_preview": safe_params,
            }
            completed.append({"step_id": step.id, "tool": step.tool, "requires_confirmation": tool_def.requires_confirmation})
            dry_run_skipped.append(step.tool)
            logger.info("dry_run skip step=%s tool=%s", step.id, step.tool)
            continue

        logger.debug("Executing step %s: tool=%r params_keys=%s", step.id, step.tool, list(resolved_params))

        try:
            from django.conf import settings as _dj_settings
            step_timeout = float(getattr(_dj_settings, "TOOL_STEP_TIMEOUT", 60))
            result = await asyncio.wait_for(
                _call_with_retry(step.tool, tool_def.fn, **resolved_params),
                timeout=step_timeout,
            )
        except asyncio.TimeoutError as exc:
            logger.error("Step %s tool %r timed out after %.0fs", step.id, step.tool, step_timeout)
            if tool_def.requires_confirmation:
                safe_params = {k: v for k, v in resolved_params.items() if k != "token_data"}
                await _record_action(user_id, step.tool, json.dumps(safe_params, default=str)[:500], "failed")
            raise ToolExecutionError(step.id, step.tool, f"timed out after {step_timeout:.0f}s", completed) from exc
        except Exception as exc:
            logger.error("Step %s tool %r raised: %s", step.id, step.tool, exc)
            if tool_def.requires_confirmation:
                safe_params = {k: v for k, v in resolved_params.items() if k != "token_data"}
                await _record_action(user_id, step.tool, json.dumps(safe_params, default=str)[:500], "failed")
            raise ToolExecutionError(step.id, step.tool, str(exc), completed) from exc

        # Compatibility hook: some tools may still return updated_token_data.
        # Current Gmail execution refreshes in CredentialService before the tool runs.
        if tool_def.requires_creds and isinstance(result, dict):
            updated = result.pop("updated_token_data", None)
            if updated is not None:
                await save_credentials(user_id, tool_def.plugin_id, updated)
                logger.debug("Persisted refreshed credentials for plugin %r", tool_def.plugin_id)

        context[step.output_var] = result
        completed.append({"step_id": step.id, "tool": step.tool, "requires_confirmation": tool_def.requires_confirmation})
        logger.debug("Step %s complete → stored in %r", step.id, step.output_var)
        logger.info(
            "execute step complete user_id=%s step_id=%s tool=%s output_var=%s result_type=%s",
            user_id,
            step.id,
            step.tool,
            step.output_var,
            type(result).__name__,
        )

        if on_step:
            await on_step(step.id, step.tool, len(completed) - 1, len(plan.steps))

        if tool_def.requires_confirmation:
            # Summarise params (exclude token_data to avoid logging credentials)
            safe_params = {k: v for k, v in resolved_params.items() if k != "token_data"}
            summary = json.dumps(safe_params, default=str)[:500]
            await _record_action(user_id, step.tool, summary, "success")

    if plan.final_output_var not in context:
        raise KeyError(
            f"final_output_var {plan.final_output_var!r} was not produced by any plan step"
        )

    final = context[plan.final_output_var]
    logger.info(
        "execute complete user_id=%s final_output_var=%s final_type=%s",
        user_id,
        plan.final_output_var,
        type(final).__name__,
    )
    # The last step should always be processing_llm, which returns a str.
    # Fallback serialization handles unexpected non-string results gracefully.
    result = final if isinstance(final, str) else json.dumps(final, indent=2)
    if dry_run_skipped:
        skipped_list = ", ".join(f"`{t}`" for t in dry_run_skipped)
        result += f"\n\n*(Dry run — the following actions were previewed but not executed: {skipped_list})*"
    return result
