"""
Web search tool — backed by the Tavily Search API.
No user credentials required; uses TAVILY_API_KEY from the environment.
"""
import asyncio
import logging
import os
from typing import Any, Dict

import requests

from tools.registry import ToolDef, register

logger = logging.getLogger(__name__)

_TAVILY_URL = "https://api.tavily.com/search"


def _api_key() -> str:
    key = os.getenv("TAVILY_API_KEY")
    if not key:
        raise RuntimeError("TAVILY_API_KEY environment variable is not set")
    return key


def _do_search(query: str, max_results: int, include_answer: bool) -> Dict[str, Any]:
    resp = requests.post(
        _TAVILY_URL,
        json={
            "api_key": _api_key(),
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
            "include_answer": include_answer,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    return {
        "answer": data.get("answer"),
        "results": [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", ""),
                "score": r.get("score", 0.0),
            }
            for r in data.get("results", [])
        ],
    }


async def web_search(
    query: str,
    max_results: int = 5,
    include_answer: bool = False,
) -> Dict[str, Any]:
    """Search the web using Tavily and return ranked results plus an optional synthesized answer."""
    max_results = max(1, min(max_results, 10))
    result = await asyncio.to_thread(_do_search, query, max_results, include_answer)
    logger.info("web.search query=%r returned=%d answer=%s", query, len(result["results"]), bool(result["answer"]))
    return result


register(ToolDef(
    name="web.search",
    display_name="Web Search",
    description=(
        "Search the web for current information. "
        "Returns a ranked list of results with titles, URLs, and content snippets. "
        "Use for current events, factual lookups, research, or any question that "
        "may require up-to-date information not in the model's training data."
    ),
    params_schema={
        "query": {
            "type": "string",
            "description": "The search query.",
            "required": True,
        },
        "max_results": {
            "type": "integer",
            "description": "Maximum number of results to return (default 5, max 10).",
            "required": False,
        },
        "include_answer": {
            "type": "boolean",
            "description": (
                "When true, Tavily returns an AI-synthesized direct answer alongside the result list. "
                "Use for factual lookups where a one-sentence answer plus sources is preferable to a raw list."
            ),
            "required": False,
        },
    },
    fn=web_search,
    requires_confirmation=False,
))

