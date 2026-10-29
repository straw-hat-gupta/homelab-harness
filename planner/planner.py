import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List

from asgiref.sync import sync_to_async
from openai import AsyncOpenAI

from planner.schemas import Plan, PlanStep

logger = logging.getLogger(__name__)

_PLAN_CACHE_PREFIX = "aiva:plan:"


def _plan_cache_key(
    prompt: str,
    model: str,
    connected_accounts: List[Dict[str, Any]] | None,
    tool_schemas: List[Dict[str, Any]],
    memories: List[Dict[str, Any]] | None = None,
) -> str:
    """Build a stable cache key for a history-free planning request.

    Args:
        prompt: User prompt to plan.
        model: Planner model name.
        connected_accounts: Active plugin/account context.
        tool_schemas: Planner-visible tool schemas.
        memories: User's persistent memories.

    Returns:
        Cache key string.
    """
    accounts = sorted((a["plugin"], a.get("account_id") or "") for a in (connected_accounts or []))
    accounts_hash = hashlib.sha256(json.dumps(accounts).encode()).hexdigest()[:16]
    schemas_hash = hashlib.sha256(json.dumps(tool_schemas, sort_keys=True).encode()).hexdigest()[:16]
    mem_pairs = sorted((m["key"], m["value"]) for m in (memories or []))
    memories_hash = hashlib.sha256(json.dumps(mem_pairs).encode()).hexdigest()[:16]
    raw = f"{model}|{prompt.strip()}|{accounts_hash}|{schemas_hash}|{memories_hash}"
    return _PLAN_CACHE_PREFIX + hashlib.sha256(raw.encode()).hexdigest()


@sync_to_async
def _cache_get(key: str):
    """Read a cached planner response.

    Args:
        key: Cache key.

    Returns:
        Cached value, or None.
    """
    from django.core.cache import cache
    return cache.get(key)


@sync_to_async
def _cache_set(key: str, value: str, ttl: int) -> None:
    """Store a planner response in cache.

    Args:
        key: Cache key.
        value: Serialized plan.
        ttl: Cache lifetime in seconds.

    Returns:
        None.
    """
    from django.core.cache import cache
    cache.set(key, value, ttl)


@dataclass
class _Usage:
    model: str
    input_tokens: int
    output_tokens: int


@sync_to_async
def _persist_usage(user_id: str, usage: _Usage, call_type: str) -> None:
    """Persist token usage for a planner-related LLM call.

    Args:
        user_id: Supabase UID of the user.
        usage: Token usage data.
        call_type: Planner call type label.

    Returns:
        None.
    """
    from django.contrib.auth import get_user_model
    from agent.models import PlannerUsage
    User = get_user_model()
    try:
        user = User.objects.get(supabase_uid=user_id)
        PlannerUsage.objects.create(
            user=user,
            model=usage.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            call_type=call_type,
        )
    except Exception:
        logger.warning("Failed to persist planner usage for user=%s", user_id, exc_info=True)

_client: AsyncOpenAI | None = None

# Default wall-clock timeout for every OpenAI call. Override via settings.PLANNER_TIMEOUT.
_DEFAULT_TIMEOUT = 60.0


def _get_client() -> AsyncOpenAI:
    """Return the shared async OpenAI client.

    Returns:
        Configured AsyncOpenAI client.
    """
    global _client
    if _client is None:
        import os
        from django.conf import settings
        api_key = getattr(settings, "OPENAI_KEY", None) or os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_KEY")
        _client = AsyncOpenAI(api_key=api_key)
    return _client


def _timeout() -> float:
    """Return planner request timeout.

    Returns:
        Timeout in seconds.
    """
    from django.conf import settings
    return float(getattr(settings, "PLANNER_TIMEOUT", _DEFAULT_TIMEOUT))


_SYSTEM_PROMPT = """\
You are a task planner. Given a user request and conversation history, produce a JSON execution \
plan using the available tools.

Rules:
1. Output ONLY a valid JSON object — no markdown fences, no commentary.
2. Each step has exactly these fields:
   - "id"         : unique string identifier (e.g. "step_1")
   - "tool"       : tool name exactly as listed below
   - "params"     : object of parameters for the tool (see each tool's "params" schema)
   - "output_var" : unique variable name to store the result in
3. Reference a prior step's result in params using the syntax "$output_var_name" as the value.
4. Credentials are injected automatically — never include token_data, api_key, or user_id in params. \
When multiple accounts are shown for a plugin, set "account_id" on that step to the specific account \
identifier (e.g. "account_id": "user@gmail.com"). Omit "account_id" when only one account exists.
5. "processing_llm" can appear at any point in the plan — use it whenever you need to \
transform, summarize, or compose data before passing it to the next step \
(e.g. write an email body, reformat API data, etc.).
6. The LAST step MUST be "processing_llm" to produce a natural-language final answer for \
the user confirming what happened or answering their question.
7. "processing_llm" params:
   - "task"   : string instruction for the LLM (what to do with the data)
   - "inputs" : object mapping a descriptive label to a "$var_ref" from a prior step
8. Set "final_output_var" to the output_var of the last step.
9. Include a "summary" field: one or two sentences starting with "I will..." describing \
exactly what the plan does. Name key specifics — email recipients, subjects, cities, \
what data is fetched or sent. This is shown to the user before execution.
10. If the user can be answered directly without calling any external tool, create a single-step \
plan using "processing_llm" with an empty or minimal "inputs" object.
11. IMPORTANT — only use tools whose plugin appears in the "Connected plugins" list below. \
If the user asks you to do something that requires a plugin that is NOT connected, do NOT \
include that tool in the plan. Instead, produce a single processing_llm step that politely \
tells the user which plugin they need to connect and where to do so (Settings → Plugins).
12. When a plan step uses "web.search", the result has this shape: \
{{"answer": "<synthesized answer or null>", "results": [{{"title": "...", "url": "...", "content": "...", "score": 0.9}}, ...]}}. \
In the final processing_llm step, instruct it to: (a) lead with the "answer" field if present, \
(b) supplement with relevant detail from "results[].content", and (c) cite sources as markdown \
links [Title](URL) using "results[].title" and "results[].url". Set include_answer=true in \
web.search params when the user is asking a factual question with a direct answer.
13. User memories are ground truth about this specific user — use them to personalise plans \
(e.g. if the user's city is stored, pre-fill location params instead of asking). \
When the user asks you to remember or forget something, use "memory.save" or "memory.delete".
14. When the user asks to save, create, or name a reusable workflow, use "workflow.save". \
The "plan" param is a complete inner plan JSON (its own "steps", "final_output_var", "summary"). \
In the inner plan, replace any param values the user would want to change between runs with \
"$input.<name>" references (e.g. "$input.keywords", "$input.recipient"). \
Add a matching entry to "input_schema" for each such reference: \
{{"name": "<name>", "type": "<string|integer|array|...>", "label": "<human-readable label>", \
"required": true/false, "default": <optional default value>}}. \
Params that are always fixed (e.g. a specific action like "summarize") should stay hardcoded.

Output schema:
{{
  "steps": [ {{ "id": "...", "tool": "...", "params": {{}}, "output_var": "...", "account_id": "<optional>" }}, ... ],
  "final_output_var": "...",
  "summary": "I will..."
}}

User memories (persistent facts about this user — treat as ground truth):
{memories}

Connected accounts (user has active credentials for these; when multiple accounts are listed for a plugin, \
set "account_id" on that step to select the correct one):
{connected_plugins}

Available tools:
{tool_schemas}

Conversation history (most recent last):
{history}
"""

_INTENT_SYSTEM = """\
A user was shown a plan summary and asked "Shall I proceed?".
Classify their reply as EXACTLY one of these three labels:
  confirm — they approve the plan and want to proceed
  cancel  — they want to stop or abandon the plan entirely
  modify  — they want to change something about the plan

OUTPUT RULES:
- Your entire response must be one of the three words: confirm, cancel, or modify.
- No punctuation, no explanation, no other words.\
"""

# Words that unambiguously mean the user approved.
_CONFIRM_TOKENS = {"confirm", "yes", "yeah", "yep", "yup", "ok", "okay", "sure",
                   "proceed", "go", "do it", "sounds good", "great", "perfect",
                   "absolutely", "affirmative", "agreed"}

# Words that unambiguously mean the user rejected.
_CANCEL_TOKENS = {"cancel", "no", "nope", "nah", "stop", "abort", "never mind",
                  "nevermind", "forget it", "don't", "dont", "discard"}


async def detect_intent(
    user_message: str,
    plan_summary: str,
    model: str | None = None,
    user_id: str | None = None,
) -> str:
    """Classify a user's response to a pending-plan prompt.

    Args:
        user_message: User reply to classify.
        plan_summary: Summary of the pending plan.
        model: Optional planner model override.
        user_id: Optional Supabase UID for usage tracking.

    Returns:
        One of `confirm`, `cancel`, or `modify`.
    """
    if model is None:
        from django.conf import settings
        model = getattr(settings, "PLANNER_MODEL", "gpt-4o-mini")

    client = _get_client()
    response = await client.chat.completions.create(
        model=model,
        temperature=0.0,
        max_tokens=10,
        timeout=_timeout(),
        messages=[
            {"role": "system", "content": _INTENT_SYSTEM},
            {"role": "user", "content": (
                f'Plan: "{plan_summary}"\n\nUser reply: "{user_message}"'
            )},
        ],
    )
    if user_id and response.usage:
        await _persist_usage(
            user_id,
            _Usage(model=model, input_tokens=response.usage.prompt_tokens, output_tokens=response.usage.completion_tokens),
            "intent",
        )
    raw = response.choices[0].message.content.strip().lower()

    # Strip punctuation for matching
    token = raw.rstrip(".,!?").split()[0] if raw.split() else raw

    if token in _CONFIRM_TOKENS or raw.startswith("confirm"):
        return "confirm"
    if token in _CANCEL_TOKENS or raw.startswith("cancel"):
        return "cancel"

    # Also check the raw user message directly for unambiguous short replies
    user_lower = user_message.strip().lower().rstrip(".,!?")
    if user_lower in _CONFIRM_TOKENS:
        return "confirm"
    if user_lower in _CANCEL_TOKENS:
        return "cancel"

    return "modify"


_REVISE_PROMPT = """\
The user has reviewed the following plan and requested a change.

Current plan:
{current_plan}

User's requested change:
"{feedback}"

Revise the plan to incorporate the change while preserving the original intent for everything \
else. Update the "summary" field to reflect the revised plan.
"""


def _build_system(
    tool_schemas: List[Dict[str, Any]],
    history: List[Dict[str, str]],
    connected_accounts: List[Dict[str, Any]] | None = None,
    memories: List[Dict[str, Any]] | None = None,
) -> str:
    """Build the planner system prompt from available context.

    Args:
        tool_schemas: Planner-visible tool descriptors.
        history: Conversation history messages.
        connected_accounts: Active plugin/account context.
        memories: User's persistent key/value memories.

    Returns:
        Rendered system prompt.
    """
    history_text = (
        "\n".join(f"{m['role'].capitalize()}: {m['content']}" for m in history)
        or "(none)"
    )
    if not connected_accounts:
        accounts_text = "(none — user has not connected any plugins)"
    else:
        from collections import defaultdict
        groups: Dict[str, list] = defaultdict(list)
        for a in connected_accounts:
            groups[a["plugin"]].append(a.get("account_id"))
        parts = []
        for plugin, ids in sorted(groups.items()):
            real_ids = [i for i in ids if i]
            parts.append(f"{plugin}: {', '.join(real_ids)}" if real_ids else plugin)
        accounts_text = "; ".join(parts)
    if memories:
        memories_text = "\n".join(f"- {m['key']}: {m['value']}" for m in memories)
    else:
        memories_text = "(none)"
    return _SYSTEM_PROMPT.format(
        tool_schemas=json.dumps(tool_schemas, indent=2),
        history=history_text,
        connected_plugins=accounts_text,
        memories=memories_text,
    )


def _build_direct_response_plan(user_message: str, history: List[Dict[str, str]]) -> Plan:
    """Build a fallback plan that answers directly without tools.

    Args:
        user_message: User request.
        history: Conversation history messages.

    Returns:
        Single-step processing LLM plan.
    """
    inputs: Dict[str, Any] = {"user_request": user_message}
    if history:
        inputs["conversation_history"] = history

    return Plan(
        steps=[
            PlanStep(
                id="step_1",
                tool="processing_llm",
                params={
                    "task": (
                        "Respond directly to the user's request without using any external tools. "
                        "Use the conversation history if it is relevant. Be concise, natural, and "
                        "do not claim to have fetched external data or performed actions."
                    ),
                    "inputs": inputs,
                },
                output_var="final_response",
            )
        ],
        final_output_var="final_response",
        summary="I will respond directly to the user's request without using external tools.",
    )


def _is_executable_plan(plan: Plan) -> bool:
    """Check whether a plan can produce its declared final output.

    Args:
        plan: Planner-produced plan.

    Returns:
        True when the final output variable is produced by a step.
    """
    if not plan.steps or not plan.final_output_var.strip():
        return False

    produced_vars = {
        step.output_var
        for step in plan.steps
        if isinstance(step.output_var, str) and step.output_var.strip()
    }
    return plan.final_output_var in produced_vars


def _normalize_plan(plan: Plan, user_message: str, history: List[Dict[str, str]]) -> Plan:
    """Replace non-executable plans with a direct response fallback.

    Args:
        plan: Planner-produced plan.
        user_message: User request.
        history: Conversation history messages.

    Returns:
        Executable plan.
    """
    if _is_executable_plan(plan):
        return plan

    logger.warning(
        "Planner returned a non-executable plan; falling back to direct response plan. "
        "steps=%d final_output_var=%r",
        len(plan.steps),
        plan.final_output_var,
    )
    return _build_direct_response_plan(user_message, history)


async def _call_planner(system: str, user_message: str, model: str) -> tuple[Plan, _Usage]:
    """Call the planner model and parse the returned plan.

    Args:
        system: Planner system prompt.
        user_message: User prompt sent to the model.
        model: Planner model name.

    Returns:
        Parsed plan and token usage data.
    """
    client = _get_client()
    response = await client.chat.completions.create(
        model=model,
        temperature=0.0,
        response_format={"type": "json_object"},
        timeout=_timeout(),
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ],
    )
    raw = response.choices[0].message.content
    logger.debug("Planner raw output: %s", raw)
    usage = _Usage(
        model=model,
        input_tokens=response.usage.prompt_tokens if response.usage else 0,
        output_tokens=response.usage.completion_tokens if response.usage else 0,
    )
    return Plan.model_validate(json.loads(raw)), usage


async def plan(
    prompt: str,
    history: List[Dict[str, str]],
    tool_schemas: List[Dict[str, Any]],
    model: str | None = None,
    connected_accounts: List[Dict[str, Any]] | None = None,
    user_id: str | None = None,
    memories: List[Dict[str, Any]] | None = None,
) -> Plan:
    """Produce a structured plan from a user prompt.

    Args:
        prompt: User's current request.
        history: Prior conversation messages.
        tool_schemas: Tool descriptors from the tool registry.
        model: Optional planner model override.
        connected_accounts: {plugin, account_id} dicts for every active credential row.
        user_id: Optional Supabase UID for usage tracking.
        memories: User's persistent key/value memories.

    Returns:
        Executable plan.
    """
    if model is None:
        from django.conf import settings
        model = getattr(settings, "PLANNER_MODEL", "gpt-4o-mini")

    from django.conf import settings as _settings
    cache_ttl = int(getattr(_settings, "PLAN_CACHE_TTL", 3600))

    # Only cache history-free requests: history changes plan params, making cached
    # plans incorrect for context-dependent queries.
    if cache_ttl > 0 and not history:
        cache_key = _plan_cache_key(prompt, model, connected_accounts, tool_schemas, memories)
        cached = await _cache_get(cache_key)
        if cached is not None:
            logger.info("plan cache hit model=%s", model)
            return Plan.model_validate_json(cached)

    system = _build_system(tool_schemas, history, connected_accounts, memories)
    planned, usage = await _call_planner(system, prompt, model)
    if user_id:
        await _persist_usage(user_id, usage, "plan")
    result = _normalize_plan(planned, prompt, history)

    if cache_ttl > 0 and not history:
        await _cache_set(cache_key, result.model_dump_json(), cache_ttl)
        logger.debug("plan cache stored model=%s ttl=%ds", model, cache_ttl)

    return result


async def revise_plan(
    current_plan: Plan,
    feedback: str,
    history: List[Dict[str, str]],
    tool_schemas: List[Dict[str, Any]],
    model: str | None = None,
    connected_accounts: List[Dict[str, Any]] | None = None,
    user_id: str | None = None,
    memories: List[Dict[str, Any]] | None = None,
) -> Plan:
    """Revise an existing plan based on user feedback.

    Args:
        current_plan: Plan the user wants to change.
        feedback: User's modification request.
        history: Prior conversation messages.
        tool_schemas: Tool descriptors from the tool registry.
        model: Optional planner model override.
        connected_accounts: {plugin, account_id} dicts for every active credential row.
        user_id: Optional Supabase UID for usage tracking.
        memories: User's persistent key/value memories.

    Returns:
        Revised executable plan.
    """
    if model is None:
        from django.conf import settings
        model = getattr(settings, "PLANNER_MODEL", "gpt-4o-mini")

    system = _build_system(tool_schemas, history, connected_accounts, memories)
    user_message = _REVISE_PROMPT.format(
        current_plan=current_plan.model_dump_json(indent=2),
        feedback=feedback,
    )
    planned, usage = await _call_planner(system, user_message, model)
    if user_id:
        await _persist_usage(user_id, usage, "revise")
    # Use the original plan summary as fallback context so a broken revised plan
    # doesn't produce a "direct response" that talks about the modification instruction.
    return _normalize_plan(planned, current_plan.summary, history)
