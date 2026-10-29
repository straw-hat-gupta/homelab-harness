"""
Google Drive tools - backed by the Google Drive API v3.
Credentials (token_data) are injected by the orchestrator via the google_drive plugin.
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

_DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
]

# Google Workspace MIME types and their plain-text export equivalents.
_EXPORTABLE_MIME_TYPES = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}
_TEXT_MIME_PREFIXES = ("text/", "application/json", "application/xml", "application/javascript")
_MAX_CONTENT_CHARS = 50_000

_FILE_FIELDS = ",".join(
    [
        "id",
        "name",
        "mimeType",
        "createdTime",
        "modifiedTime",
        "size",
        "owners(emailAddress,displayName)",
        "webViewLink",
        "trashed",
        "starred",
        "parents",
    ]
)


def _build_service(token_data: dict):
    """Build an authenticated Google Drive API client.

    Args:
        token_data: OAuth token data injected by the orchestrator.

    Returns:
        Google Drive API service object.
    """
    creds = Credentials(
        token=token_data["access_token"],
        refresh_token=token_data.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=_DRIVE_SCOPES,
    )
    return build("drive", "v3", http=authorized_http(creds), cache_discovery=False)


def _normalize_owner(owner: dict) -> Dict[str, str]:
    """Normalize a Drive owner object.

    Args:
        owner: Raw owner data from the Drive API.

    Returns:
        Owner dictionary with stable keys.
    """
    return {
        "email": owner.get("emailAddress", ""),
        "display_name": owner.get("displayName", ""),
    }


def _file_to_dict(file_obj: dict) -> Dict[str, Any]:
    """Normalize a Drive file object.

    Args:
        file_obj: Raw file metadata from the Drive API.

    Returns:
        File metadata dictionary with stable keys.
    """
    return {
        "id": file_obj.get("id", ""),
        "name": file_obj.get("name", ""),
        "mime_type": file_obj.get("mimeType", ""),
        "created_time": file_obj.get("createdTime", ""),
        "modified_time": file_obj.get("modifiedTime", ""),
        "size": file_obj.get("size"),
        "owners": [_normalize_owner(owner) for owner in file_obj.get("owners", [])],
        "web_view_link": file_obj.get("webViewLink", ""),
        "trashed": file_obj.get("trashed", False),
        "starred": file_obj.get("starred", False),
        "parents": file_obj.get("parents", []),
    }


def _folder_clause(folder_id: Optional[str]) -> str:
    """Build an optional Drive query clause for a parent folder.

    Args:
        folder_id: Optional Drive folder ID.

    Returns:
        Query fragment for folder filtering.
    """
    if not folder_id:
        return ""
    return f" and '{folder_id}' in parents"


async def drive_list_files(
    token_data: dict,
    max_results: int = 10,
    folder_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List recent non-trashed Drive files.

    Args:
        token_data: OAuth token data injected by the orchestrator.
        max_results: Maximum number of files to return.
        folder_id: Optional parent folder ID.

    Returns:
        List of normalized file metadata rows.
    """
    def _fetch():
        """Fetch Drive files from the blocking Google API client.

        Returns:
            List of normalized file metadata rows.
        """
        service = _build_service(token_data)
        query = f"trashed = false{_folder_clause(folder_id)}"
        result = service.files().list(
            q=query,
            pageSize=max(1, min(max_results, 100)),
            orderBy="viewedByMeTime desc, modifiedTime desc",
            fields=f"files({_FILE_FIELDS})",
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
        ).execute()
        return [_file_to_dict(file_obj) for file_obj in result.get("files", [])]

    files = await asyncio.to_thread(_fetch)
    logger.info("drive.list_files returned=%d folder_id=%s", len(files), folder_id)
    return files


async def drive_search_files(
    token_data: dict,
    query: str,
    max_results: int = 10,
    folder_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Search Drive files by name.

    Args:
        token_data: OAuth token data injected by the orchestrator.
        query: Filename search string.
        max_results: Maximum number of files to return.
        folder_id: Optional parent folder ID.

    Returns:
        List of normalized file metadata rows.
    """
    def _fetch():
        """Fetch matching Drive files from the blocking Google API client.

        Returns:
            List of normalized file metadata rows.
        """
        service = _build_service(token_data)
        escaped_query = query.replace("'", "\\'")
        drive_query = (
            f"trashed = false and name contains '{escaped_query}'{_folder_clause(folder_id)}"
        )
        result = service.files().list(
            q=drive_query,
            pageSize=max(1, min(max_results, 100)),
            orderBy="modifiedTime desc",
            fields=f"files({_FILE_FIELDS})",
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
        ).execute()
        return [_file_to_dict(file_obj) for file_obj in result.get("files", [])]

    files = await asyncio.to_thread(_fetch)
    logger.info(
        "drive.search_files returned=%d query=%r folder_id=%s",
        len(files),
        query,
        folder_id,
    )
    return files


async def drive_get_file_metadata(
    token_data: dict,
    file_id: str,
) -> Dict[str, Any]:
    """Return metadata for one Drive file.

    Args:
        token_data: OAuth token data injected by the orchestrator.
        file_id: Google Drive file ID.

    Returns:
        Normalized file metadata dictionary.
    """
    def _fetch():
        """Fetch one Drive file from the blocking Google API client.

        Returns:
            Normalized file metadata dictionary.
        """
        service = _build_service(token_data)
        file_obj = service.files().get(
            fileId=file_id,
            fields=_FILE_FIELDS,
            supportsAllDrives=True,
        ).execute()
        return _file_to_dict(file_obj)

    file_data = await asyncio.to_thread(_fetch)
    logger.info("drive.get_file_metadata file_id=%s", file_id)
    return file_data


async def drive_read_file(token_data: dict, file_id: str) -> Dict[str, Any]:
    """Read the text content of a Google Drive file.

    Args:
        token_data: OAuth token data injected by the orchestrator.
        file_id: Google Drive file ID.

    Returns:
        File name, MIME type, and text content (truncated to 50,000 characters).
    """
    def _fetch():
        import io
        from googleapiclient.http import MediaIoBaseDownload

        service = _build_service(token_data)
        meta = service.files().get(
            fileId=file_id, fields="id,name,mimeType", supportsAllDrives=True
        ).execute()
        name = meta.get("name", "")
        mime_type = meta.get("mimeType", "")

        export_mime = _EXPORTABLE_MIME_TYPES.get(mime_type)
        buf = io.BytesIO()

        if export_mime:
            request = service.files().export_media(fileId=file_id, mimeType=export_mime)
        elif any(mime_type.startswith(p) for p in _TEXT_MIME_PREFIXES):
            request = service.files().get_media(fileId=file_id)
        else:
            return {
                "file_id": file_id,
                "name": name,
                "mime_type": mime_type,
                "content": None,
                "error": f"File type {mime_type!r} cannot be read as text.",
            }

        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

        content = buf.getvalue().decode("utf-8", errors="ignore")
        truncated = len(content) > _MAX_CONTENT_CHARS
        return {
            "file_id": file_id,
            "name": name,
            "mime_type": mime_type,
            "content": content[:_MAX_CONTENT_CHARS],
            "char_count": len(content),
            "truncated": truncated,
        }

    result = await asyncio.to_thread(_fetch)
    logger.info(
        "drive.read_file file_id=%s name=%r truncated=%s",
        file_id,
        result.get("name"),
        result.get("truncated", False),
    )
    return result


register(ToolDef(
    name="drive.list_files",
    display_name="List Drive Files",
    description=(
        "List the user's recent Google Drive files and folders. "
        "Returns metadata only, not file contents."
    ),
    params_schema={
        "max_results": {
            "type": "integer",
            "description": "Maximum number of files to return (default 10, max 100).",
            "required": False,
        },
        "folder_id": {
            "type": "string",
            "description": "Optional parent folder ID to restrict results to one folder.",
            "required": False,
        },
    },
    fn=drive_list_files,
    requires_creds=True,
    plugin_id="google_drive",
    requires_confirmation=False,
))

register(ToolDef(
    name="drive.search_files",
    display_name="Search Drive Files",
    description=(
        "Search the user's Google Drive files by name. "
        "Returns metadata only, not file contents."
    ),
    params_schema={
        "query": {
            "type": "string",
            "description": "Filename search string.",
            "required": True,
        },
        "max_results": {
            "type": "integer",
            "description": "Maximum number of files to return (default 10, max 100).",
            "required": False,
        },
        "folder_id": {
            "type": "string",
            "description": "Optional parent folder ID to restrict results to one folder.",
            "required": False,
        },
    },
    fn=drive_search_files,
    requires_creds=True,
    plugin_id="google_drive",
    requires_confirmation=False,
))

register(ToolDef(
    name="drive.get_file_metadata",
    display_name="Get File Metadata",
    description="Return detailed metadata for a single Google Drive file or folder.",
    params_schema={
        "file_id": {
            "type": "string",
            "description": "Google Drive file ID.",
            "required": True,
        },
    },
    fn=drive_get_file_metadata,
    requires_creds=True,
    plugin_id="google_drive",
    requires_confirmation=False,
))

register(ToolDef(
    name="drive.read_file",
    display_name="Read File Content",
    description=(
        "Read the text content of a Google Drive file. "
        "Supports Google Docs (exported as plain text), Google Sheets (exported as CSV), "
        "Google Slides (exported as plain text), and plain-text files. "
        "Binary files (images, PDFs, videos) cannot be read and will return an error. "
        "Content is truncated at 50,000 characters for large files."
    ),
    params_schema={
        "file_id": {
            "type": "string",
            "description": "Google Drive file ID from a prior drive.list_files or drive.search_files step.",
            "required": True,
        },
    },
    fn=drive_read_file,
    requires_creds=True,
    plugin_id="google_drive",
    requires_confirmation=False,
))
