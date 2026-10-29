"""
LLM-as-a-tool: synthesizes, summarizes, or transforms data from prior plan steps
into a natural-language string that can be used by subsequent steps or returned
as the final answer.
"""
import json
import logging
from typing import Any, Dict

from openai import AsyncOpenAI

from tools.registry import ToolDef, register

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


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


def _timeout() -> int:
    """Return processing LLM request timeout.

    Returns:
        Timeout in seconds.
    """
    from django.conf import settings
    return getattr(settings, "PROCESSING_LLM_TIMEOUT", 60)


def _max_tokens() -> int:
    """Return processing LLM output token limit.

    Returns:
        Maximum output tokens.
    """
    from django.conf import settings
    return getattr(settings, "PROCESSING_LLM_MAX_TOKENS", 1024)


async def call_processing_llm(
    task: str,
    inputs: Dict[str, Any],
    model: str | None = None,
) -> str:
    """Synthesize or transform tool outputs into text.

    Args:
        task: Instruction describing what to produce.
        inputs: Dict of labeled data from prior plan steps (already resolved by orchestrator).
        model: Optional LLM model override.

    Returns:
        Final string response from the LLM.
    """
    if model is None:
        from django.conf import settings
        model = getattr(settings, "PROCESSING_LLM_MODEL", "gpt-4o-mini")

    context_parts = []
    for label, value in inputs.items():
        serialized = value if isinstance(value, str) else json.dumps(value, indent=2)
        context_parts.append(f"## {label}\n{serialized}")

    context_text = "\n\n".join(context_parts) if context_parts else "(no additional context)"
    user_message = f"Task: {task}\n\nContext:\n{context_text}"

    client = _get_client()
    response = await client.chat.completions.create(
        model=model,
        temperature=0.0,
        max_tokens=_max_tokens(),
        timeout=_timeout(),
        messages=[
            {
                "role": "system",
                "content": "You are a helpful assistant. Complete the task using the provided context.",
            },
            {"role": "user", "content": user_message},
        ],
    )

    return response.choices[0].message.content


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

register(ToolDef(
    name="processing_llm",
    display_name="LLM Processing",
    description=(
        "Call the LLM to synthesize, summarize, or transform data from prior steps into a "
        "natural-language string. Can appear at any point in the plan — use it to compose "
        "content (e.g. an email body) before passing to the next step, or as the final step "
        "to produce a human-readable answer."
    ),
    params_schema={
        "task": {
            "type": "string",
            "description": "Instruction for the LLM describing what to produce.",
            "required": True,
        },
        "inputs": {
            "type": "object",
            "description": (
                "Dict mapping a descriptive label to a '$var_ref' from a prior step's output_var. "
                "Example: {\"weather\": \"$weather_data\"}"
            ),
            "required": False,
        },
    },
    fn=call_processing_llm,
))

