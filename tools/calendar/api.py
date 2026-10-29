"""
Google Calendar tools - backed by the Google Calendar API v3.
Credentials (token_data) are injected by the orchestrator via the google_calendar plugin.
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

from django.conf import settings
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from tools.google_http import authorized_http
from tools.registry import ToolDef, register

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Service builder
# ---------------------------------------------------------------------------

_CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]


def _build_service(token_data: dict):
    """Build an authenticated Google Calendar API client.

    Args:
        token_data: OAuth token data injected by the orchestrator.

    Returns:
        Google Calendar API service object.
    """
    creds = Credentials(
        token=token_data["access_token"],
        refresh_token=token_data.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=_CALENDAR_SCOPES,
    )
    return build("calendar", "v3", http=authorized_http(creds), cache_discovery=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _event_to_dict(event: dict) -> Dict[str, Any]:
    """Normalize a Google Calendar event.

    Args:
        event: Raw event object from the Calendar API.

    Returns:
        Event dictionary with stable response keys.
    """
    start = event.get("start", {})
    end = event.get("end", {})
    return {
        "id": event.get("id", ""),
        "summary": event.get("summary", "(no title)"),
        "description": event.get("description", ""),
        "location": event.get("location", ""),
        "start": start.get("dateTime") or start.get("date", ""),
        "end": end.get("dateTime") or end.get("date", ""),
        "html_link": event.get("htmlLink", ""),
        "status": event.get("status", ""),
        "attendees": [
            {"email": a.get("email", ""), "response": a.get("responseStatus", "")}
            for a in event.get("attendees", [])
        ],
        "recurrence": event.get("recurrence", []),
        "recurring_event_id": event.get("recurringEventId", ""),
    }


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------

async def calendar_list_events(
    token_data: dict,
    max_results: int = 10,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
    query: Optional[str] = None,
    calendar_id: str = "primary",
) -> List[Dict[str, Any]]:
    """
    List upcoming calendar events.

    Args:
        time_min: RFC3339 timestamp lower bound (e.g. "2024-01-01T00:00:00Z").
        time_max: RFC3339 timestamp upper bound.
        query:    Free-text search query (searches summary, description, location).
    """
    def _fetch():
        """Fetch events from the blocking Google Calendar API client.

        Returns:
            List of normalized event dictionaries.
        """
        service = _build_service(token_data)
        kwargs: Dict[str, Any] = {
            "calendarId": calendar_id,
            "maxResults": max(1, min(max_results, 250)),
            "singleEvents": True,
            "orderBy": "startTime",
        }
        if time_min:
            kwargs["timeMin"] = time_min
        if time_max:
            kwargs["timeMax"] = time_max
        if query:
            kwargs["q"] = query
        result = service.events().list(**kwargs).execute()
        return [_event_to_dict(e) for e in result.get("items", [])]

    events = await asyncio.to_thread(_fetch)
    logger.info("calendar.list_events returned=%d", len(events))
    return events


async def calendar_create_event(
    token_data: dict,
    summary: str,
    start: str,
    end: str,
    description: str = "",
    location: str = "",
    attendees: Optional[List[str]] = None,
    calendar_id: str = "primary",
    recurrence: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Create a calendar event.

    Args:
        summary:    Event title.
        start:      RFC3339 datetime string (e.g. "2024-06-15T10:00:00-07:00") or date ("2024-06-15").
        end:        RFC3339 datetime string or date.
        attendees:  List of email addresses to invite.
        recurrence: List of RRULE/EXRULE strings for recurring events,
                    e.g. ["RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR"].
    """
    def _create():
        """Create an event using the blocking Google Calendar API client.

        Returns:
            Normalized event dictionary.
        """
        service = _build_service(token_data)
        # Determine if all-day (date) or timed (dateTime)
        time_key = "date" if len(start) <= 10 else "dateTime"
        body: Dict[str, Any] = {
            "summary": summary,
            "start": {time_key: start},
            "end": {time_key: end},
        }
        if description:
            body["description"] = description
        if location:
            body["location"] = location
        if attendees:
            body["attendees"] = [{"email": e} for e in attendees]
        if recurrence:
            body["recurrence"] = recurrence

        event = service.events().insert(calendarId=calendar_id, body=body).execute()
        return _event_to_dict(event)

    event = await asyncio.to_thread(_create)
    logger.info("calendar.create_event id=%s summary=%r", event["id"], event["summary"])
    return event


async def calendar_update_event(
    token_data: dict,
    event_id: str,
    summary: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    description: Optional[str] = None,
    location: Optional[str] = None,
    calendar_id: str = "primary",
) -> Dict[str, Any]:
    """
    Update an existing calendar event. Only provided fields are changed (patch semantics).

    Args:
        event_id: The Google Calendar event ID.
    """
    def _update():
        """Patch an event using the blocking Google Calendar API client.

        Returns:
            Normalized event dictionary.
        """
        service = _build_service(token_data)
        # Fetch current event first (required for patch)
        current = service.events().get(calendarId=calendar_id, eventId=event_id).execute()
        patch: Dict[str, Any] = {}
        if summary is not None:
            patch["summary"] = summary
        if description is not None:
            patch["description"] = description
        if location is not None:
            patch["location"] = location
        if start is not None:
            time_key = "date" if len(start) <= 10 else "dateTime"
            patch["start"] = {time_key: start}
        if end is not None:
            time_key = "date" if len(end) <= 10 else "dateTime"
            patch["end"] = {time_key: end}
        current.update(patch)
        updated = service.events().update(
            calendarId=calendar_id, eventId=event_id, body=current
        ).execute()
        return _event_to_dict(updated)

    event = await asyncio.to_thread(_update)
    logger.info("calendar.update_event id=%s", event["id"])
    return event


async def calendar_delete_event(
    token_data: dict,
    event_id: str,
    calendar_id: str = "primary",
) -> Dict[str, Any]:
    """
    Delete a calendar event permanently.

    Args:
        event_id: The Google Calendar event ID to delete.
    """
    def _delete():
        """Delete an event using the blocking Google Calendar API client.

        Returns:
            Deletion confirmation dictionary.
        """
        service = _build_service(token_data)
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        return {"deleted": True, "event_id": event_id}

    result = await asyncio.to_thread(_delete)
    logger.info("calendar.delete_event id=%s", event_id)
    return result


async def calendar_list_calendars(
    token_data: dict,
) -> List[Dict[str, Any]]:
    """List calendars accessible to the user.

    Args:
        token_data: OAuth token data injected by the orchestrator.

    Returns:
        List of calendar metadata dictionaries.
    """
    def _list():
        """Fetch calendars from the blocking Google Calendar API client.

        Returns:
            List of calendar metadata dictionaries.
        """
        service = _build_service(token_data)
        result = service.calendarList().list().execute()
        return [
            {
                "id": cal.get("id", ""),
                "summary": cal.get("summary", ""),
                "description": cal.get("description", ""),
                "access_role": cal.get("accessRole", ""),
                "primary": cal.get("primary", False),
            }
            for cal in result.get("items", [])
        ]

    calendars = await asyncio.to_thread(_list)
    logger.info("calendar.list_calendars returned=%d", len(calendars))
    return calendars


async def calendar_get_free_busy(
    token_data: dict,
    time_min: str,
    time_max: str,
    calendar_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Check when the user's calendars are busy over a time range.

    Args:
        token_data: OAuth token data injected by the orchestrator.
        time_min: RFC3339 start of the query window, e.g. "2024-06-15T00:00:00Z".
        time_max: RFC3339 end of the query window.
        calendar_ids: Calendar IDs to query (defaults to ["primary"]).

    Returns:
        Dictionary mapping each calendar ID to its list of busy slots.
    """
    def _fetch():
        service = _build_service(token_data)
        items = [{"id": cid} for cid in (calendar_ids or ["primary"])]
        resp = service.freebusy().query(body={
            "timeMin": time_min,
            "timeMax": time_max,
            "items": items,
        }).execute()
        result: Dict[str, Any] = {}
        for cal_id, data in resp.get("calendars", {}).items():
            result[cal_id] = {
                "busy": data.get("busy", []),
                "errors": data.get("errors", []),
            }
        return {"time_min": time_min, "time_max": time_max, "calendars": result}

    data = await asyncio.to_thread(_fetch)
    busy_count = sum(len(v["busy"]) for v in data["calendars"].values())
    logger.info("calendar.get_free_busy time_min=%s time_max=%s busy_slots=%d", time_min, time_max, busy_count)
    return data


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

register(ToolDef(
    name="calendar.list_events",
    display_name="List Calendar Events",
    description=(
        "List the user's Google Calendar events. "
        "Returns event titles, times, locations, and attendees."
    ),
    params_schema={
        "max_results": {"type": "integer", "description": "Maximum number of events to return (default 10, max 250).", "required": False},
        "time_min": {"type": "string", "description": "RFC3339 start time filter, e.g. '2024-06-01T00:00:00Z'. Defaults to now if omitted.", "required": False},
        "time_max": {"type": "string", "description": "RFC3339 end time filter.", "required": False},
        "query": {"type": "string", "description": "Free-text search across event title, description, and location.", "required": False},
        "calendar_id": {"type": "string", "description": "Calendar ID (default 'primary').", "required": False},
    },
    fn=calendar_list_events,
    requires_creds=True,
    plugin_id="google_calendar",
    requires_confirmation=False,
))

register(ToolDef(
    name="calendar.create_event",
    display_name="Create Calendar Event",
    description="Create a new event on the user's Google Calendar.",
    params_schema={
        "summary": {"type": "string", "description": "Event title.", "required": True},
        "start": {"type": "string", "description": "Start time as RFC3339 datetime (e.g. '2024-06-15T10:00:00-07:00') or date ('2024-06-15') for all-day events.", "required": True},
        "end": {"type": "string", "description": "End time in the same format as start.", "required": True},
        "description": {"type": "string", "description": "Event description or notes.", "required": False},
        "location": {"type": "string", "description": "Location string.", "required": False},
        "attendees": {"type": "array", "items": {"type": "string"}, "description": "List of attendee email addresses.", "required": False},
        "calendar_id": {"type": "string", "description": "Calendar ID (default 'primary').", "required": False},
        "recurrence": {
            "type": "array",
            "items": {"type": "string"},
            "description": "RRULE strings for recurring events, e.g. ['RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR']. Omit for one-off events.",
            "required": False,
        },
    },
    fn=calendar_create_event,
    requires_creds=True,
    plugin_id="google_calendar",
    requires_confirmation=True,
))

register(ToolDef(
    name="calendar.update_event",
    display_name="Update Calendar Event",
    description="Update an existing event on the user's Google Calendar. Only supplied fields are changed.",
    params_schema={
        "event_id": {"type": "string", "description": "The Google Calendar event ID.", "required": True},
        "summary": {"type": "string", "description": "New event title (omit to keep current).", "required": False},
        "start": {"type": "string", "description": "New start time as RFC3339 datetime or date (omit to keep current).", "required": False},
        "end": {"type": "string", "description": "New end time (omit to keep current).", "required": False},
        "description": {"type": "string", "description": "New description (omit to keep current).", "required": False},
        "location": {"type": "string", "description": "New location (omit to keep current).", "required": False},
        "calendar_id": {"type": "string", "description": "Calendar ID (default 'primary').", "required": False},
    },
    fn=calendar_update_event,
    requires_creds=True,
    plugin_id="google_calendar",
    requires_confirmation=True,
))

register(ToolDef(
    name="calendar.delete_event",
    display_name="Delete Calendar Event",
    description="Permanently delete an event from the user's Google Calendar.",
    params_schema={
        "event_id": {"type": "string", "description": "The Google Calendar event ID to delete.", "required": True},
        "calendar_id": {"type": "string", "description": "Calendar ID (default 'primary').", "required": False},
    },
    fn=calendar_delete_event,
    requires_creds=True,
    plugin_id="google_calendar",
    requires_confirmation=True,
))

register(ToolDef(
    name="calendar.get_free_busy",
    display_name="Get Free/Busy",
    description=(
        "Check when the user is free or busy over a time range. "
        "Returns a list of busy slots per calendar. "
        "Use this to answer questions like 'when am I free next week?' "
        "or 'do I have any conflicts on Thursday?'"
    ),
    params_schema={
        "time_min": {
            "type": "string",
            "description": "RFC3339 start of the window, e.g. '2024-06-15T00:00:00Z'.",
            "required": True,
        },
        "time_max": {
            "type": "string",
            "description": "RFC3339 end of the window.",
            "required": True,
        },
        "calendar_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Calendar IDs to check (default ['primary']).",
            "required": False,
        },
    },
    fn=calendar_get_free_busy,
    requires_creds=True,
    plugin_id="google_calendar",
    requires_confirmation=False,
))

register(ToolDef(
    name="calendar.list_calendars",
    display_name="List Calendars",
    description=(
        "List all Google Calendars the user has access to. "
        "Returns each calendar's ID, name, and access role. "
        "Use this to discover non-primary calendar IDs before listing or creating events."
    ),
    params_schema={},
    fn=calendar_list_calendars,
    requires_creds=True,
    plugin_id="google_calendar",
    requires_confirmation=False,
))
