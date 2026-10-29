"""
Notion tools — backed by the Notion API v1 (https://api.notion.com/v1).

All tools use plugin_id="notion".

Credentials (token_data) are injected by the orchestrator.
No SDK — calls are plain requests with a Bearer token and the Notion-Version header.
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

import requests as _requests

from orchestrator.exceptions import PluginNotConnectedError
from tools.registry import ToolDef, register

logger = logging.getLogger(__name__)

_NOTION = "https://api.notion.com/v1"
_NOTION_VERSION = "2022-06-28"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _headers(token_data: dict) -> dict:
    return {
        "Authorization": f"Bearer {token_data['access_token']}",
        "Notion-Version": _NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _raise_for_status(resp: _requests.Response) -> None:
    try:
        resp.raise_for_status()
    except _requests.HTTPError as exc:
        if resp.status_code == 401:
            raise PluginNotConnectedError("notion") from exc
        raise _requests.HTTPError(
            f"Notion API error {resp.status_code}: {resp.text}",
            response=resp,
        ) from exc


def _get(token_data: dict, path: str, params: dict | None = None) -> dict:
    resp = _requests.get(f"{_NOTION}{path}", headers=_headers(token_data), params=params or {}, timeout=30)
    _raise_for_status(resp)
    return resp.json()


def _post(token_data: dict, path: str, body: dict | None = None) -> dict:
    resp = _requests.post(f"{_NOTION}{path}", headers=_headers(token_data), json=body or {}, timeout=30)
    _raise_for_status(resp)
    return resp.json()


def _patch(token_data: dict, path: str, body: dict) -> dict:
    resp = _requests.patch(f"{_NOTION}{path}", headers=_headers(token_data), json=body, timeout=30)
    _raise_for_status(resp)
    return resp.json()


def _title_property_name(token_data: dict, database_id: str) -> str:
    """Return the name of a database's title property (often 'Name', not 'title')."""
    db = _get(token_data, f"/databases/{database_id}")
    for name, prop in db.get("properties", {}).items():
        if prop.get("type") == "title":
            return name
    return "title"


def _content_to_blocks(content: str) -> List[Dict[str, Any]]:
    return [
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": line}}]},
        }
        for line in content.split("\n")
    ]


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

async def notion_search(
    token_data: dict,
    query: str,
    filter_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Search Notion pages and databases the integration can access.

    Args:
        token_data: OAuth token data injected by the orchestrator.
        query: Text to search for in page/database titles.
        filter_type: Optional object filter — 'page' or 'database'.

    Returns:
        List of matching Notion objects.
    """
    def _run():
        body: Dict[str, Any] = {"query": query}
        if filter_type:
            body["filter"] = {"property": "object", "value": filter_type}
        return _post(token_data, "/search", body).get("results", [])

    results = await asyncio.to_thread(_run)
    logger.info("notion.search query=%r returned=%d", query, len(results))
    return results


async def notion_get_page(
    token_data: dict,
    page_id: str,
) -> Dict[str, Any]:
    """Fetch a Notion page's properties and its top-level child blocks (body).

    Args:
        token_data: OAuth token data injected by the orchestrator.
        page_id: Notion page ID.

    Returns:
        Dictionary with 'page' (properties) and 'blocks' (top-level content).
    """
    def _run():
        page = _get(token_data, f"/pages/{page_id}")
        blocks = _get(token_data, f"/blocks/{page_id}/children").get("results", [])
        return {"page": page, "blocks": blocks}

    result = await asyncio.to_thread(_run)
    logger.info("notion.get_page page_id=%s blocks=%d", page_id, len(result["blocks"]))
    return result


async def notion_create_page(
    token_data: dict,
    parent_id: str,
    title: str,
    content: str = "",
    is_database: bool = False,
) -> Dict[str, Any]:
    """Create a Notion page under a page parent or as a database row.

    Args:
        token_data: OAuth token data injected by the orchestrator.
        parent_id: Parent page ID, or database ID when is_database is True.
        title: Page title.
        content: Optional body text; each line becomes a paragraph block.
        is_database: Create the page as a row in a database (default False).

    Returns:
        The created Notion page object.
    """
    def _run():
        if is_database:
            parent = {"database_id": parent_id}
            title_key = _title_property_name(token_data, parent_id)
        else:
            parent = {"page_id": parent_id}
            title_key = "title"
        properties = {title_key: {"title": [{"text": {"content": title}}]}}
        body: Dict[str, Any] = {"parent": parent, "properties": properties}
        if content:
            body["children"] = _content_to_blocks(content)
        return _post(token_data, "/pages", body)

    page = await asyncio.to_thread(_run)
    logger.info("notion.create_page parent_id=%s title=%r id=%s", parent_id, title, page.get("id"))
    return page


async def notion_update_page(
    token_data: dict,
    page_id: str,
    title: Optional[str] = None,
    properties: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Update a Notion page's properties. Only supplied fields are changed.

    Args:
        token_data: OAuth token data injected by the orchestrator.
        page_id: Notion page ID.
        title: New title (omit to keep current).
        properties: Raw Notion property values to set (merged with title).

    Returns:
        The updated Notion page object.
    """
    def _run():
        props: Dict[str, Any] = dict(properties or {})
        if title is not None:
            props["title"] = {"title": [{"text": {"content": title}}]}
        return _patch(token_data, f"/pages/{page_id}", {"properties": props})

    page = await asyncio.to_thread(_run)
    logger.info("notion.update_page page_id=%s", page_id)
    return page


async def notion_append_blocks(
    token_data: dict,
    page_id: str,
    blocks: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Append block children to a Notion page or block.

    Args:
        token_data: OAuth token data injected by the orchestrator.
        page_id: Notion page or block ID to append to.
        blocks: List of Notion block objects, passed through verbatim.

    Returns:
        Notion response containing the appended block list.
    """
    def _run():
        return _patch(token_data, f"/blocks/{page_id}/children", {"children": blocks})

    result = await asyncio.to_thread(_run)
    logger.info("notion.append_blocks page_id=%s count=%d", page_id, len(blocks))
    return result


async def notion_list_databases(
    token_data: dict,
    page_size: int = 100,
) -> List[Dict[str, Any]]:
    """List Notion databases the integration can access.

    Args:
        token_data: OAuth token data injected by the orchestrator.
        page_size: Maximum databases to return (default 100).

    Returns:
        List of Notion database objects.
    """
    def _run():
        body = {
            "filter": {"property": "object", "value": "database"},
            "page_size": max(1, min(page_size, 100)),
        }
        return _post(token_data, "/search", body).get("results", [])

    results = await asyncio.to_thread(_run)
    logger.info("notion.list_databases returned=%d", len(results))
    return results


async def notion_query_database(
    token_data: dict,
    database_id: str,
    filter: Optional[Dict[str, Any]] = None,
    sorts: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Query rows (pages) in a Notion database.

    Args:
        token_data: OAuth token data injected by the orchestrator.
        database_id: Notion database ID.
        filter: Optional Notion filter object.
        sorts: Optional list of Notion sort objects.

    Returns:
        List of page objects matching the query.
    """
    def _run():
        body: Dict[str, Any] = {}
        if filter:
            body["filter"] = filter
        if sorts:
            body["sorts"] = sorts
        return _post(token_data, f"/databases/{database_id}/query", body).get("results", [])

    results = await asyncio.to_thread(_run)
    logger.info("notion.query_database database_id=%s returned=%d", database_id, len(results))
    return results


# ---------------------------------------------------------------------------
# Registration (plugin_id="notion")
# ---------------------------------------------------------------------------

register(ToolDef(
    name="notion.search",
    display_name="Search Notion",
    description="Search Notion pages and databases by title. Optionally filter to only 'page' or 'database' objects.",
    params_schema={
        "query": {"type": "string", "description": "Text to search for in page/database titles.", "required": True, "hint": "input"},
        "filter_type": {"type": "string", "description": "Optional object filter: 'page' or 'database'.", "required": False},
    },
    fn=notion_search,
    requires_creds=True,
    plugin_id="notion",
))

register(ToolDef(
    name="notion.get_page",
    display_name="Get Page",
    description="Fetch a Notion page's properties together with its top-level child blocks (the page body).",
    params_schema={
        "page_id": {"type": "string", "description": "Notion page ID.", "required": True},
    },
    fn=notion_get_page,
    requires_creds=True,
    plugin_id="notion",
))

register(ToolDef(
    name="notion.create_page",
    display_name="Create Page",
    description=(
        "Create a Notion page under a parent page, or as a row in a database when is_database is true. "
        "Optional content is split on newlines into paragraph blocks."
    ),
    params_schema={
        "parent_id": {"type": "string", "description": "Parent page ID, or database ID when is_database is true.", "required": True},
        "title": {"type": "string", "description": "Page title.", "required": True, "hint": "input"},
        "content": {"type": "string", "description": "Optional body text; each line becomes a paragraph.", "required": False, "hint": "input"},
        "is_database": {"type": "boolean", "description": "Create as a row in a database (default false).", "required": False},
    },
    fn=notion_create_page,
    requires_creds=True,
    plugin_id="notion",
    requires_confirmation=True,
))

register(ToolDef(
    name="notion.update_page",
    display_name="Update Page",
    description="Update a Notion page's properties. Only supplied fields are changed.",
    params_schema={
        "page_id": {"type": "string", "description": "Notion page ID.", "required": True},
        "title": {"type": "string", "description": "New title (omit to keep current).", "required": False, "hint": "input"},
        "properties": {"type": "object", "description": "Raw Notion property values to set.", "required": False},
    },
    fn=notion_update_page,
    requires_creds=True,
    plugin_id="notion",
    requires_confirmation=True,
))

register(ToolDef(
    name="notion.append_blocks",
    display_name="Append Blocks",
    description="Append block children (verbatim Notion block objects) to a Notion page or block.",
    params_schema={
        "page_id": {"type": "string", "description": "Notion page or block ID to append to.", "required": True},
        "blocks": {"type": "array", "items": {"type": "object"}, "description": "List of Notion block objects.", "required": True},
    },
    fn=notion_append_blocks,
    requires_creds=True,
    plugin_id="notion",
    requires_confirmation=True,
))

register(ToolDef(
    name="notion.list_databases",
    display_name="List Databases",
    description="List Notion databases the integration can access.",
    params_schema={
        "page_size": {"type": "integer", "description": "Maximum databases to return (default 100, max 100).", "required": False},
    },
    fn=notion_list_databases,
    requires_creds=True,
    plugin_id="notion",
))

register(ToolDef(
    name="notion.query_database",
    display_name="Query Database",
    description="Query rows (pages) in a Notion database with optional Notion filter and sort objects.",
    params_schema={
        "database_id": {"type": "string", "description": "Notion database ID.", "required": True},
        "filter": {"type": "object", "description": "Optional Notion filter object.", "required": False},
        "sorts": {"type": "array", "items": {"type": "object"}, "description": "Optional list of Notion sort objects.", "required": False},
    },
    fn=notion_query_database,
    requires_creds=True,
    plugin_id="notion",
))
