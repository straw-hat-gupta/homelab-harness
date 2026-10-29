"""
Tests for tools/drive/api.py.

All tests mock the Google Drive API service so no real credentials are needed.
"""

from backend.testing import run_async
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
    return run_async(coro)


@override_settings(**GOOGLE_SETTINGS)
@patch("tools.drive.api.build")
class BuildServiceTests(TestCase):
    def test_credentials_include_client_id_and_secret_and_scopes(self, mock_build):
        from tools.drive.api import _build_service

        _build_service(TOKEN)

        http = mock_build.call_args.kwargs["http"]
        creds = http.credentials
        self.assertEqual(creds.client_id, "test-client-id")
        self.assertEqual(creds.client_secret, "test-client-secret")
        self.assertEqual(
            list(creds.scopes),
            # drive.read_file downloads content, which metadata.readonly cannot do.
            ["https://www.googleapis.com/auth/drive.readonly"],
        )
        self.assertEqual(http.timeout, 15)
        mock_build.assert_called_once_with(
            "drive",
            "v3",
            http=http,
            cache_discovery=False,
        )


@override_settings(**GOOGLE_SETTINGS)
@patch("tools.drive.api.build")
class DriveToolBehaviorTests(TestCase):
    def test_list_files_returns_normalized_rows(self, mock_build):
        from tools.drive.api import drive_list_files

        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.files().list().execute.return_value = {
            "files": [
                {
                    "id": "file-1",
                    "name": "Quarterly Plan",
                    "mimeType": "application/vnd.google-apps.document",
                    "createdTime": "2026-05-10T10:00:00Z",
                    "modifiedTime": "2026-05-11T12:00:00Z",
                    "size": "1234",
                    "owners": [{"emailAddress": "owner@example.com", "displayName": "Owner"}],
                    "webViewLink": "https://drive.google.com/file/d/file-1/view",
                    "trashed": False,
                    "starred": True,
                    "parents": ["folder-1"],
                }
            ]
        }

        result = _run(drive_list_files(TOKEN, max_results=5))

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "file-1")
        self.assertEqual(result[0]["mime_type"], "application/vnd.google-apps.document")
        self.assertEqual(result[0]["owners"][0]["email"], "owner@example.com")

    def test_search_files_includes_query_and_folder_filter(self, mock_build):
        from tools.drive.api import drive_search_files

        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.files().list().execute.return_value = {"files": []}

        result = _run(drive_search_files(TOKEN, query="quarterly plan", folder_id="folder-1"))

        self.assertEqual(result, [])
        kwargs = mock_service.files().list.call_args.kwargs
        self.assertIn("quarterly plan", kwargs["q"])
        self.assertIn("'folder-1' in parents", kwargs["q"])

    def test_get_file_metadata_returns_normalized_row(self, mock_build):
        from tools.drive.api import drive_get_file_metadata

        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.files().get().execute.return_value = {
            "id": "file-2",
            "name": "Roadmap",
            "mimeType": "application/pdf",
            "createdTime": "2026-05-12T10:00:00Z",
            "modifiedTime": "2026-05-12T11:00:00Z",
            "size": "42",
            "owners": [{"emailAddress": "owner@example.com", "displayName": "Owner"}],
            "webViewLink": "https://drive.google.com/file/d/file-2/view",
            "trashed": False,
            "starred": False,
            "parents": [],
        }

        result = _run(drive_get_file_metadata(TOKEN, file_id="file-2"))

        self.assertEqual(result["id"], "file-2")
        self.assertEqual(result["name"], "Roadmap")
        self.assertEqual(result["mime_type"], "application/pdf")

    def test_drive_client_errors_propagate(self, mock_build):
        from tools.drive.api import drive_list_files

        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.files().list().execute.side_effect = RuntimeError("drive boom")

        with self.assertRaises(RuntimeError):
            _run(drive_list_files(TOKEN))


@override_settings(**GOOGLE_SETTINGS)
class DriveToolRegistrationTests(TestCase):
    def test_all_three_tools_registered(self):
        from tools.registry import _REGISTRY

        self.assertIn("drive.list_files", _REGISTRY)
        self.assertIn("drive.search_files", _REGISTRY)
        self.assertIn("drive.get_file_metadata", _REGISTRY)

    def test_tools_require_google_drive_credentials(self):
        from tools.registry import _REGISTRY

        for name in ("drive.list_files", "drive.search_files", "drive.get_file_metadata"):
            tool = _REGISTRY[name]
            self.assertTrue(tool.requires_creds)
            self.assertEqual(tool.plugin_id, "google_drive")
            self.assertFalse(tool.requires_confirmation)
