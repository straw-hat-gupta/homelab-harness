"""
Tests for tools/calendar/api.py.

All tests mock the Google API service so no real credentials are needed.
"""
import asyncio
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

TOKEN = {
    "access_token": "access",
    "refresh_token": "refresh",
}

GOOGLE_SETTINGS = {
    "GOOGLE_CLIENT_ID": "test-client-id",
    "GOOGLE_CLIENT_SECRET": "test-client-secret",
}


def _run(coro):
    return asyncio.run(coro)


@override_settings(**GOOGLE_SETTINGS)
@patch("tools.calendar.api.build")
class BuildServiceTests(TestCase):
    """_build_service builds scoped credentials and a bounded HTTP transport."""

    def test_credentials_include_client_id_and_secret(self, mock_build):
        from tools.calendar.api import _build_service

        _build_service(TOKEN)

        http = mock_build.call_args.kwargs["http"]
        creds = http.credentials
        self.assertEqual(creds.client_id, "test-client-id")
        self.assertEqual(creds.client_secret, "test-client-secret")
        self.assertIsNotNone(creds.scopes)
        self.assertEqual(http.timeout, 15)
        mock_build.assert_called_once_with(
            "calendar",
            "v3",
            http=http,
            cache_discovery=False,
        )


@override_settings(**GOOGLE_SETTINGS)
@patch("tools.calendar.api.build")
class CalendarListEventsTests(TestCase):
    def test_returns_mapped_events(self, mock_build):
        from tools.calendar.api import calendar_list_events

        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.events().list().execute.return_value = {
            "items": [
                {
                    "id": "evt1",
                    "summary": "Team standup",
                    "start": {"dateTime": "2026-05-10T09:00:00Z"},
                    "end": {"dateTime": "2026-05-10T09:30:00Z"},
                }
            ]
        }

        result = _run(calendar_list_events(TOKEN))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "evt1")
        self.assertEqual(result[0]["summary"], "Team standup")

    def test_empty_calendar_returns_empty_list(self, mock_build):
        from tools.calendar.api import calendar_list_events

        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.events().list().execute.return_value = {"items": []}

        result = _run(calendar_list_events(TOKEN))
        self.assertEqual(result, [])


@override_settings(**GOOGLE_SETTINGS)
@patch("tools.calendar.api.build")
class CalendarDeleteEventTests(TestCase):
    def test_delete_returns_confirmation(self, mock_build):
        from tools.calendar.api import calendar_delete_event

        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.events().delete().execute.return_value = None

        result = _run(calendar_delete_event(TOKEN, event_id="evt1"))
        self.assertTrue(result["deleted"])
        self.assertEqual(result["event_id"], "evt1")

    def test_delete_calls_api_with_correct_ids(self, mock_build):
        from tools.calendar.api import calendar_delete_event

        mock_service = MagicMock()
        mock_build.return_value = mock_service

        _run(calendar_delete_event(TOKEN, event_id="evt2", calendar_id="work@example.com"))

        mock_service.events().delete.assert_called_with(
            calendarId="work@example.com", eventId="evt2"
        )


@override_settings(**GOOGLE_SETTINGS)
@patch("tools.calendar.api.build")
class CalendarListCalendarsTests(TestCase):
    def test_returns_calendar_list(self, mock_build):
        from tools.calendar.api import calendar_list_calendars

        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.calendarList().list().execute.return_value = {
            "items": [
                {
                    "id": "primary",
                    "summary": "Ivan Guo",
                    "accessRole": "owner",
                    "primary": True,
                },
                {
                    "id": "work@example.com",
                    "summary": "Work",
                    "accessRole": "writer",
                    "primary": False,
                },
            ]
        }

        result = _run(calendar_list_calendars(TOKEN))
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["id"], "primary")
        self.assertTrue(result[0]["primary"])
        self.assertEqual(result[1]["id"], "work@example.com")
        self.assertFalse(result[1]["primary"])

    def test_empty_calendar_list(self, mock_build):
        from tools.calendar.api import calendar_list_calendars

        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.calendarList().list().execute.return_value = {"items": []}

        result = _run(calendar_list_calendars(TOKEN))
        self.assertEqual(result, [])


@override_settings(**GOOGLE_SETTINGS)
class CalendarToolRegistrationTests(TestCase):
    def test_all_five_tools_registered(self):
        from tools.registry import _REGISTRY
        self.assertIn("calendar.list_events", _REGISTRY)
        self.assertIn("calendar.create_event", _REGISTRY)
        self.assertIn("calendar.update_event", _REGISTRY)
        self.assertIn("calendar.delete_event", _REGISTRY)
        self.assertIn("calendar.list_calendars", _REGISTRY)

    def test_delete_event_requires_confirmation(self):
        from tools.registry import _REGISTRY
        self.assertTrue(_REGISTRY["calendar.delete_event"].requires_confirmation)

    def test_list_calendars_no_confirmation(self):
        from tools.registry import _REGISTRY
        self.assertFalse(_REGISTRY["calendar.list_calendars"].requires_confirmation)
