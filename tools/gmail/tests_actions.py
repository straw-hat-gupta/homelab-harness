"""
Tests for the Gmail action tools added in Batch 2:
trash_email, mark_read, mark_unread, add_label, remove_label, create_draft.
"""

from backend.testing import run_async
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

TOKEN = {"access_token": "access", "refresh_token": "refresh"}
GOOGLE_SETTINGS = {
    "GOOGLE_CLIENT_ID": "test-client-id",
    "GOOGLE_CLIENT_SECRET": "test-client-secret",
}


def _run(coro):
    return run_async(coro)


@override_settings(**GOOGLE_SETTINGS)
@patch("tools.gmail.api.build")
class BuildServiceTests(TestCase):
    def test_builds_gmail_service_with_bounded_http_transport(self, mock_build):
        from tools.gmail.api import _build_service

        _build_service(TOKEN)

        http = mock_build.call_args.kwargs["http"]
        creds = http.credentials
        self.assertEqual(creds.client_id, "test-client-id")
        self.assertEqual(creds.client_secret, "test-client-secret")
        self.assertIn("mail.google.com", list(creds.scopes)[0])
        self.assertEqual(http.timeout, 15)
        mock_build.assert_called_once_with(
            "gmail",
            "v1",
            http=http,
            cache_discovery=False,
        )


@override_settings(**GOOGLE_SETTINGS)
@patch("tools.gmail.api.build")
class TrashEmailTests(TestCase):
    def test_returns_trashed_status(self, mock_build):
        from tools.gmail.api import _gmail

        mock_service = MagicMock()
        mock_build.return_value = mock_service

        result = _run(_gmail.trash_email(TOKEN, msg_id="msg1"))
        self.assertEqual(result["status"], "trashed")
        self.assertEqual(result["msg_id"], "msg1")

    def test_calls_trash_api(self, mock_build):
        from tools.gmail.api import _gmail

        mock_service = MagicMock()
        mock_build.return_value = mock_service

        _run(_gmail.trash_email(TOKEN, msg_id="msg2"))
        mock_service.users().messages().trash.assert_called_with(userId="me", id="msg2")


@override_settings(**GOOGLE_SETTINGS)
@patch("tools.gmail.api.build")
class MarkReadUnreadTests(TestCase):
    def test_mark_read_removes_unread_label(self, mock_build):
        from tools.gmail.api import _gmail

        mock_service = MagicMock()
        mock_build.return_value = mock_service

        result = _run(_gmail.mark_read(TOKEN, msg_id="msg3"))
        self.assertEqual(result["status"], "marked_read")
        mock_service.users().messages().modify.assert_called_with(
            userId="me", id="msg3", body={"removeLabelIds": ["UNREAD"]}
        )

    def test_mark_unread_adds_unread_label(self, mock_build):
        from tools.gmail.api import _gmail

        mock_service = MagicMock()
        mock_build.return_value = mock_service

        result = _run(_gmail.mark_unread(TOKEN, msg_id="msg4"))
        self.assertEqual(result["status"], "marked_unread")
        mock_service.users().messages().modify.assert_called_with(
            userId="me", id="msg4", body={"addLabelIds": ["UNREAD"]}
        )


@override_settings(**GOOGLE_SETTINGS)
@patch("tools.gmail.api.build")
class AddRemoveLabelTests(TestCase):
    def _mock_labels(self, mock_service):
        mock_service.users().labels().list().execute.return_value = {
            "labels": [
                {"id": "Label_123", "name": "Work"},
                {"id": "Label_456", "name": "Personal"},
            ]
        }

    def test_add_label_resolves_name_to_id(self, mock_build):
        from tools.gmail.api import _gmail

        mock_service = MagicMock()
        mock_build.return_value = mock_service
        self._mock_labels(mock_service)

        result = _run(_gmail.add_label(TOKEN, msg_id="msg5", label_name="Work"))
        self.assertEqual(result["status"], "label_added")
        self.assertEqual(result["label"], "Work")
        mock_service.users().messages().modify.assert_called_with(
            userId="me", id="msg5", body={"addLabelIds": ["Label_123"]}
        )

    def test_remove_label_resolves_name_to_id(self, mock_build):
        from tools.gmail.api import _gmail

        mock_service = MagicMock()
        mock_build.return_value = mock_service
        self._mock_labels(mock_service)

        result = _run(_gmail.remove_label(TOKEN, msg_id="msg6", label_name="Personal"))
        self.assertEqual(result["status"], "label_removed")
        mock_service.users().messages().modify.assert_called_with(
            userId="me", id="msg6", body={"removeLabelIds": ["Label_456"]}
        )

    def test_add_label_unknown_name_raises(self, mock_build):
        from tools.gmail.api import _gmail

        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.users().labels().list().execute.return_value = {"labels": []}

        with self.assertRaises(ValueError):
            _run(_gmail.add_label(TOKEN, msg_id="msg7", label_name="DoesNotExist"))


@override_settings(**GOOGLE_SETTINGS)
@patch("tools.gmail.api.build")
class CreateDraftTests(TestCase):
    def test_returns_draft_id(self, mock_build):
        from tools.gmail.api import _gmail

        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.users().drafts().create().execute.return_value = {"id": "draft_abc"}

        result = _run(_gmail.create_draft(TOKEN, to=["bob@example.com"], subject="Hi", body="Hello"))
        self.assertEqual(result["status"], "draft_created")
        self.assertEqual(result["draft_id"], "draft_abc")

    def test_calls_drafts_create_api(self, mock_build):
        from tools.gmail.api import _gmail

        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.users().drafts().create().execute.return_value = {"id": "d1"}

        _run(_gmail.create_draft(TOKEN, to=["a@b.com"], subject="Test", body="Body"))
        self.assertTrue(mock_service.users().drafts().create.called)
        call_kwargs = mock_service.users().drafts().create.call_args.kwargs
        self.assertEqual(call_kwargs["userId"], "me")
        self.assertIn("raw", call_kwargs["body"]["message"])


class GmailActionRegistrationTests(TestCase):
    def test_new_tools_registered(self):
        from tools.registry import _REGISTRY
        for name in [
            "gmail.trash_email",
            "gmail.mark_read",
            "gmail.mark_unread",
            "gmail.add_label",
            "gmail.remove_label",
            "gmail.create_draft",
        ]:
            self.assertIn(name, _REGISTRY, f"{name} not in registry")

    def test_trash_requires_confirmation(self):
        from tools.registry import _REGISTRY
        self.assertTrue(_REGISTRY["gmail.trash_email"].requires_confirmation)

    def test_mark_read_no_confirmation(self):
        from tools.registry import _REGISTRY
        self.assertFalse(_REGISTRY["gmail.mark_read"].requires_confirmation)

    def test_create_draft_no_confirmation(self):
        from tools.registry import _REGISTRY
        self.assertFalse(_REGISTRY["gmail.create_draft"].requires_confirmation)
