"""
Outlook / Microsoft 365 tools — backed by the Microsoft Graph API v1.0.

Mail tools use plugin_id="outlook".
Calendar tools use plugin_id="outlook_calendar".

Credentials (token_data) are injected by the orchestrator.
No SDK — calls are plain requests with a Bearer token.
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

import requests as _requests

from tools.registry import ToolDef, register

logger = logging.getLogger(__name__)

_GRAPH = "https://graph.microsoft.com/v1.0"

_MSG_SELECT = ",".join([
    "id", "conversationId", "subject", "from", "toRecipients",
    "bodyPreview", "receivedDateTime", "hasAttachments", "isRead", "importance",
])

_EVT_SELECT = ",".join([
    "id", "subject", "bodyPreview", "start", "end", "location",
    "attendees", "organizer", "webLink", "isOnlineMeeting", "onlineMeeting",
    "recurrence",
])


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _auth(token_data: dict) -> dict:
    return {"Authorization": f"Bearer {token_data['access_token']}"}


def _json_headers(token_data: dict) -> dict:
    return {**_auth(token_data), "Content-Type": "application/json"}


def _get(token_data: dict, path: str, params: dict | None = None) -> dict:
    resp = _requests.get(f"{_GRAPH}{path}", headers=_auth(token_data), params=params or {}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _post(token_data: dict, path: str, body: dict | None = None) -> _requests.Response:
    resp = _requests.post(f"{_GRAPH}{path}", headers=_json_headers(token_data), json=body or {}, timeout=30)
    resp.raise_for_status()
    return resp


def _patch(token_data: dict, path: str, body: dict) -> dict:
    resp = _requests.patch(f"{_GRAPH}{path}", headers=_json_headers(token_data), json=body, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _delete(token_data: dict, path: str) -> None:
    resp = _requests.delete(f"{_GRAPH}{path}", headers=_auth(token_data), timeout=30)
    resp.raise_for_status()


# ---------------------------------------------------------------------------
# Normalizers
# ---------------------------------------------------------------------------

def _msg_to_dict(msg: dict) -> Dict[str, Any]:
    from_ea = msg.get("from", {}).get("emailAddress", {})
    sender = f"{from_ea.get('name', '')} <{from_ea.get('address', '')}>".strip(" <>")
    return {
        "id": msg.get("id", ""),
        "conversation_id": msg.get("conversationId", ""),
        "subject": msg.get("subject", "(no subject)"),
        "sender": sender,
        "recipients": ", ".join(
            r.get("emailAddress", {}).get("address", "")
            for r in msg.get("toRecipients", [])
        ),
        "body_preview": msg.get("bodyPreview", ""),
        "received_at": msg.get("receivedDateTime", ""),
        "is_read": msg.get("isRead", True),
        "has_attachments": msg.get("hasAttachments", False),
        "importance": msg.get("importance", "normal"),
    }


def _evt_to_dict(event: dict) -> Dict[str, Any]:
    start = event.get("start", {})
    end = event.get("end", {})
    return {
        "id": event.get("id", ""),
        "subject": event.get("subject", "(no title)"),
        "body_preview": event.get("bodyPreview", ""),
        "start": start.get("dateTime", ""),
        "end": end.get("dateTime", ""),
        "timezone": start.get("timeZone", "UTC"),
        "location": event.get("location", {}).get("displayName", ""),
        "is_online": event.get("isOnlineMeeting", False),
        "join_url": (event.get("onlineMeeting") or {}).get("joinUrl", ""),
        "organizer": event.get("organizer", {}).get("emailAddress", {}).get("address", ""),
        "attendees": [
            {
                "email": a.get("emailAddress", {}).get("address", ""),
                "response": a.get("status", {}).get("response", ""),
            }
            for a in event.get("attendees", [])
        ],
        "web_link": event.get("webLink", ""),
        "recurrence": event.get("recurrence") or {},
    }


# ---------------------------------------------------------------------------
# Mail tools
# ---------------------------------------------------------------------------

async def outlook_get_unread_emails(
    token_data: dict,
    max_results: int = 50,
) -> List[Dict[str, Any]]:
    """Fetch unread Outlook messages.

    Args:
        token_data: OAuth token data injected by the orchestrator.
        max_results: Maximum messages to return (default 50, max 100).

    Returns:
        List of normalized message dictionaries.
    """
    def _fetch():
        data = _get(token_data, "/me/messages", {
            "$top": max(1, min(max_results, 100)),
            "$filter": "isRead eq false",
            "$select": _MSG_SELECT,
            "$orderby": "receivedDateTime DESC",
        })
        return [_msg_to_dict(m) for m in data.get("value", [])]

    messages = await asyncio.to_thread(_fetch)
    logger.info("outlook.get_unread_emails returned=%d", len(messages))
    return messages


async def outlook_get_emails(
    token_data: dict,
    max_results: int = 50,
    folder: str = "inbox",
) -> List[Dict[str, Any]]:
    """Fetch recent Outlook messages from a folder.

    Args:
        token_data: OAuth token data injected by the orchestrator.
        max_results: Maximum messages to return (default 50, max 100).
        folder: Well-known folder name — inbox, sentitems, drafts, deleteditems (default inbox).

    Returns:
        List of normalized message dictionaries.
    """
    def _fetch():
        data = _get(token_data, f"/me/mailFolders/{folder}/messages", {
            "$top": max(1, min(max_results, 100)),
            "$select": _MSG_SELECT,
            "$orderby": "receivedDateTime DESC",
        })
        return [_msg_to_dict(m) for m in data.get("value", [])]

    messages = await asyncio.to_thread(_fetch)
    logger.info("outlook.get_emails folder=%s returned=%d", folder, len(messages))
    return messages


async def outlook_search_emails(
    token_data: dict,
    query: str,
    max_results: int = 50,
) -> List[Dict[str, Any]]:
    """Search Outlook messages using a keyword query.

    Args:
        token_data: OAuth token data injected by the orchestrator.
        query: Keyword or KQL query (e.g. 'subject:budget' or 'from:john').
        max_results: Maximum messages to return (default 50, max 100).

    Returns:
        List of normalized message dictionaries.
    """
    def _fetch():
        # $search and $filter cannot be combined; $orderby is not supported with $search
        data = _get(token_data, "/me/messages", {
            "$top": max(1, min(max_results, 100)),
            "$search": f'"{query}"',
            "$select": _MSG_SELECT,
        })
        return [_msg_to_dict(m) for m in data.get("value", [])]

    messages = await asyncio.to_thread(_fetch)
    logger.info("outlook.search_emails query=%r returned=%d", query, len(messages))
    return messages


async def outlook_send_email(
    token_data: dict,
    to: List[str],
    subject: str,
    body: str,
    cc: Optional[List[str]] = None,
    bcc: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Send an email via Outlook.

    Args:
        token_data: OAuth token data injected by the orchestrator.
        to: Recipient email addresses.
        subject: Email subject.
        body: Plain-text email body.
        cc: Optional CC recipients.
        bcc: Optional BCC recipients.

    Returns:
        Send confirmation.
    """
    def _send():
        message: Dict[str, Any] = {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": addr}} for addr in to],
        }
        if cc:
            message["ccRecipients"] = [{"emailAddress": {"address": addr}} for addr in cc]
        if bcc:
            message["bccRecipients"] = [{"emailAddress": {"address": addr}} for addr in bcc]
        _post(token_data, "/me/sendMail", {"message": message})
        return {"status": "success"}

    result = await asyncio.to_thread(_send)
    logger.info("outlook.send_email to=%s subject=%r", to, subject)
    return result


async def outlook_reply_email(
    token_data: dict,
    message_id: str,
    body: str,
) -> Dict[str, Any]:
    """Reply to an Outlook message in-thread.

    Args:
        token_data: OAuth token data injected by the orchestrator.
        message_id: Outlook message ID of the email to reply to.
        body: Plain-text reply body.

    Returns:
        Reply confirmation.
    """
    def _reply():
        _post(token_data, f"/me/messages/{message_id}/reply", {"comment": body})
        return {"status": "success", "message_id": message_id}

    result = await asyncio.to_thread(_reply)
    logger.info("outlook.reply_email message_id=%s", message_id)
    return result


# ---------------------------------------------------------------------------
# Calendar tools
# ---------------------------------------------------------------------------

async def outlook_calendar_list_events(
    token_data: dict,
    max_results: int = 10,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List Outlook Calendar events.

    Args:
        token_data: OAuth token data injected by the orchestrator.
        max_results: Maximum events to return (default 10, max 100).
        time_min: ISO 8601 start filter, e.g. '2024-06-15T00:00:00Z'.
        time_max: ISO 8601 end filter.

    Returns:
        List of normalized event dictionaries.
    """
    def _fetch():
        params: Dict[str, Any] = {
            "$top": max(1, min(max_results, 100)),
            "$select": _EVT_SELECT,
        }
        if time_min and time_max:
            path = "/me/calendarView"
            params["startDateTime"] = time_min
            params["endDateTime"] = time_max
            params["$orderby"] = "start/dateTime"
        else:
            path = "/me/events"
            params["$orderby"] = "start/dateTime"
        data = _get(token_data, path, params)
        return [_evt_to_dict(e) for e in data.get("value", [])]

    events = await asyncio.to_thread(_fetch)
    logger.info("outlook_calendar.list_events returned=%d", len(events))
    return events


async def outlook_calendar_create_event(
    token_data: dict,
    subject: str,
    start: str,
    end: str,
    description: str = "",
    location: str = "",
    attendees: Optional[List[str]] = None,
    timezone: str = "UTC",
    is_online_meeting: bool = False,
) -> Dict[str, Any]:
    """Create an Outlook Calendar event.

    Args:
        token_data: OAuth token data injected by the orchestrator.
        subject: Event title.
        start: ISO 8601 datetime, e.g. '2024-06-15T10:00:00'.
        end: ISO 8601 datetime.
        description: Optional body text.
        location: Optional location string.
        attendees: Optional list of attendee email addresses.
        timezone: IANA timezone name (default 'UTC').
        is_online_meeting: Create a Teams meeting link (default false).

    Returns:
        Normalized event dictionary.
    """
    def _create():
        body: Dict[str, Any] = {
            "subject": subject,
            "start": {"dateTime": start, "timeZone": timezone},
            "end": {"dateTime": end, "timeZone": timezone},
            "isOnlineMeeting": is_online_meeting,
        }
        if description:
            body["body"] = {"contentType": "Text", "content": description}
        if location:
            body["location"] = {"displayName": location}
        if attendees:
            body["attendees"] = [
                {"emailAddress": {"address": addr}, "type": "required"}
                for addr in attendees
            ]
        resp = _post(token_data, "/me/events", body)
        return _evt_to_dict(resp.json())

    event = await asyncio.to_thread(_create)
    logger.info("outlook_calendar.create_event id=%s subject=%r", event["id"], event["subject"])
    return event


async def outlook_calendar_update_event(
    token_data: dict,
    event_id: str,
    subject: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    description: Optional[str] = None,
    location: Optional[str] = None,
    timezone: str = "UTC",
) -> Dict[str, Any]:
    """Update an existing Outlook Calendar event. Only supplied fields are changed.

    Args:
        token_data: OAuth token data injected by the orchestrator.
        event_id: Outlook event ID.
        subject: New title (omit to keep current).
        start: New start datetime (omit to keep current).
        end: New end datetime (omit to keep current).
        description: New body text (omit to keep current).
        location: New location (omit to keep current).
        timezone: IANA timezone for start/end values (default 'UTC').

    Returns:
        Updated normalized event dictionary.
    """
    def _update():
        patch: Dict[str, Any] = {}
        if subject is not None:
            patch["subject"] = subject
        if start is not None:
            patch["start"] = {"dateTime": start, "timeZone": timezone}
        if end is not None:
            patch["end"] = {"dateTime": end, "timeZone": timezone}
        if description is not None:
            patch["body"] = {"contentType": "Text", "content": description}
        if location is not None:
            patch["location"] = {"displayName": location}
        return _evt_to_dict(_patch(token_data, f"/me/events/{event_id}", patch))

    event = await asyncio.to_thread(_update)
    logger.info("outlook_calendar.update_event id=%s", event_id)
    return event


async def outlook_calendar_delete_event(
    token_data: dict,
    event_id: str,
) -> Dict[str, Any]:
    """Permanently delete an Outlook Calendar event.

    Args:
        token_data: OAuth token data injected by the orchestrator.
        event_id: Outlook event ID to delete.

    Returns:
        Deletion confirmation.
    """
    def _del():
        _delete(token_data, f"/me/events/{event_id}")
        return {"deleted": True, "event_id": event_id}

    result = await asyncio.to_thread(_del)
    logger.info("outlook_calendar.delete_event id=%s", event_id)
    return result


async def outlook_calendar_get_free_busy(
    token_data: dict,
    time_min: str,
    time_max: str,
) -> Dict[str, Any]:
    """Check when the user is free or busy over a time range.

    Queries the user's own calendar via calendarView and returns the list
    of events (busy slots) in the window.

    Args:
        token_data: OAuth token data injected by the orchestrator.
        time_min: ISO 8601 start of the window, e.g. '2024-06-15T00:00:00Z'.
        time_max: ISO 8601 end of the window.

    Returns:
        List of events in the time range (each represents a busy slot).
    """
    def _fetch():
        data = _get(token_data, "/me/calendarView", {
            "startDateTime": time_min,
            "endDateTime": time_max,
            "$select": _EVT_SELECT,
            "$orderby": "start/dateTime",
            "$top": 100,
        })
        events = [_evt_to_dict(e) for e in data.get("value", [])]
        return {
            "time_min": time_min,
            "time_max": time_max,
            "busy_slots": events,
        }

    result = await asyncio.to_thread(_fetch)
    logger.info(
        "outlook_calendar.get_free_busy time_min=%s time_max=%s busy_slots=%d",
        time_min, time_max, len(result["busy_slots"]),
    )
    return result


# ---------------------------------------------------------------------------
# Registration — Mail (plugin_id="outlook")
# ---------------------------------------------------------------------------

register(ToolDef(
    name="outlook.get_unread_emails",
    display_name="Get Unread Emails",
    description="Fetch unread emails from Outlook / Microsoft 365.",
    params_schema={
        "max_results": {"type": "integer", "description": "Maximum messages to return (default 50, max 100).", "required": False},
    },
    fn=outlook_get_unread_emails,
    requires_creds=True,
    plugin_id="outlook",
))

register(ToolDef(
    name="outlook.get_emails",
    display_name="Get Emails",
    description="Fetch recent emails from an Outlook folder (inbox, sentitems, drafts, deleteditems).",
    params_schema={
        "max_results": {"type": "integer", "description": "Maximum messages to return (default 50, max 100).", "required": False},
        "folder": {"type": "string", "description": "Folder name: inbox, sentitems, drafts, deleteditems (default inbox).", "required": False},
    },
    fn=outlook_get_emails,
    requires_creds=True,
    plugin_id="outlook",
))

register(ToolDef(
    name="outlook.search_emails",
    display_name="Search Emails",
    description=(
        "Search Outlook emails by keyword or KQL query. "
        "Supports 'subject:budget', 'from:john@example.com', or plain keywords."
    ),
    params_schema={
        "query": {"type": "string", "description": "Keyword or KQL query string.", "required": True, "hint": "input"},
        "max_results": {"type": "integer", "description": "Maximum messages to return (default 50, max 100).", "required": False},
    },
    fn=outlook_search_emails,
    requires_creds=True,
    plugin_id="outlook",
))

register(ToolDef(
    name="outlook.send_email",
    display_name="Send Email",
    description="Send a plain-text email via Outlook.",
    params_schema={
        "to": {"type": "array", "items": {"type": "string"}, "description": "Recipient email addresses.", "required": True, "hint": "input"},
        "subject": {"type": "string", "description": "Email subject.", "required": True, "hint": "input"},
        "body": {"type": "string", "description": "Plain-text email body.", "required": True, "hint": "input"},
        "cc": {"type": "array", "items": {"type": "string"}, "description": "Optional CC recipients.", "required": False},
        "bcc": {"type": "array", "items": {"type": "string"}, "description": "Optional BCC recipients.", "required": False},
    },
    fn=outlook_send_email,
    requires_creds=True,
    plugin_id="outlook",
    requires_confirmation=True,
))

register(ToolDef(
    name="outlook.reply_email",
    display_name="Reply to Email",
    description=(
        "Reply to an Outlook message in-thread. "
        "The reply is automatically addressed to the sender. "
        "The message_id comes from a prior outlook.get_* or search step."
    ),
    params_schema={
        "message_id": {"type": "string", "description": "Outlook message ID of the email to reply to.", "required": True},
        "body": {"type": "string", "description": "Plain-text reply body.", "required": True, "hint": "input"},
    },
    fn=outlook_reply_email,
    requires_creds=True,
    plugin_id="outlook",
    requires_confirmation=True,
))


# ---------------------------------------------------------------------------
# Registration — Calendar (plugin_id="outlook_calendar")
# ---------------------------------------------------------------------------

register(ToolDef(
    name="outlook_calendar.list_events",
    display_name="List Calendar Events",
    description=(
        "List Outlook Calendar events. "
        "Provide time_min and time_max to restrict to a date range; "
        "omit for upcoming events."
    ),
    params_schema={
        "max_results": {"type": "integer", "description": "Maximum events to return (default 10, max 100).", "required": False},
        "time_min": {"type": "string", "description": "ISO 8601 start filter, e.g. '2024-06-15T00:00:00Z'.", "required": False},
        "time_max": {"type": "string", "description": "ISO 8601 end filter.", "required": False},
    },
    fn=outlook_calendar_list_events,
    requires_creds=True,
    plugin_id="outlook_calendar",
))

register(ToolDef(
    name="outlook_calendar.create_event",
    display_name="Create Calendar Event",
    description="Create a new event on the user's Outlook Calendar.",
    params_schema={
        "subject": {"type": "string", "description": "Event title.", "required": True, "hint": "input"},
        "start": {"type": "string", "description": "Start datetime in ISO 8601, e.g. '2024-06-15T10:00:00'.", "required": True, "hint": "input"},
        "end": {"type": "string", "description": "End datetime in ISO 8601.", "required": True, "hint": "input"},
        "description": {"type": "string", "description": "Event body/notes.", "required": False},
        "location": {"type": "string", "description": "Location string.", "required": False},
        "attendees": {"type": "array", "items": {"type": "string"}, "description": "Attendee email addresses.", "required": False},
        "timezone": {"type": "string", "description": "IANA timezone name (default 'UTC').", "required": False},
        "is_online_meeting": {"type": "boolean", "description": "Create a Teams meeting link (default false).", "required": False},
    },
    fn=outlook_calendar_create_event,
    requires_creds=True,
    plugin_id="outlook_calendar",
    requires_confirmation=True,
))

register(ToolDef(
    name="outlook_calendar.update_event",
    display_name="Update Calendar Event",
    description="Update an existing Outlook Calendar event. Only supplied fields are changed.",
    params_schema={
        "event_id": {"type": "string", "description": "Outlook event ID.", "required": True},
        "subject": {"type": "string", "description": "New title (omit to keep current).", "required": False},
        "start": {"type": "string", "description": "New start datetime in ISO 8601 (omit to keep current).", "required": False},
        "end": {"type": "string", "description": "New end datetime (omit to keep current).", "required": False},
        "description": {"type": "string", "description": "New body text (omit to keep current).", "required": False},
        "location": {"type": "string", "description": "New location (omit to keep current).", "required": False},
        "timezone": {"type": "string", "description": "IANA timezone for start/end values (default 'UTC').", "required": False},
    },
    fn=outlook_calendar_update_event,
    requires_creds=True,
    plugin_id="outlook_calendar",
    requires_confirmation=True,
))

register(ToolDef(
    name="outlook_calendar.delete_event",
    display_name="Delete Calendar Event",
    description="Permanently delete an Outlook Calendar event.",
    params_schema={
        "event_id": {"type": "string", "description": "Outlook event ID to delete.", "required": True},
    },
    fn=outlook_calendar_delete_event,
    requires_creds=True,
    plugin_id="outlook_calendar",
    requires_confirmation=True,
))

register(ToolDef(
    name="outlook_calendar.get_free_busy",
    display_name="Get Free/Busy",
    description=(
        "Check when the user is free or busy by listing all calendar events in a time range. "
        "Use this to answer 'when am I free next week?' or 'do I have conflicts on Thursday?'"
    ),
    params_schema={
        "time_min": {"type": "string", "description": "ISO 8601 start of the window, e.g. '2024-06-15T00:00:00Z'.", "required": True},
        "time_max": {"type": "string", "description": "ISO 8601 end of the window.", "required": True},
    },
    fn=outlook_calendar_get_free_busy,
    requires_creds=True,
    plugin_id="outlook_calendar",
))
