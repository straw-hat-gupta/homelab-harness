"""
Direct Gmail API calls. No MCP, subprocess, or sub-agent.

Each method accepts token_data (injected by the orchestrator) and assumes the
credential has already been refreshed by CredentialService when needed.
"""

import asyncio
import base64
import logging
from email.header import decode_header
from email.mime.text import MIMEText
from base64 import urlsafe_b64decode
from typing import Any, List, Optional

from django.conf import settings
from django.core.cache import cache
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from tools.google_http import authorized_http
from tools.registry import ToolDef, register

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

from pydantic import BaseModel


class EmailMessage(BaseModel):
    msg_id: str
    thread_id: str
    subject: str
    sender: str
    recipients: str
    body: str
    snippet: str
    has_attachments: bool
    date: str
    star: bool
    label: str


class EmailMessages(BaseModel):
    count: int
    messages: List[EmailMessage]
    next_page_token: Optional[str] = None


# ---------------------------------------------------------------------------
# Gmail message parser
# ---------------------------------------------------------------------------

def _parse_gmail_message(raw_msg: dict) -> EmailMessage:
    """Parse a raw Gmail message into the tool response model.

    Args:
        raw_msg: Raw Gmail message object from the Gmail API.

    Returns:
        Parsed email message.
    """
    msg_id = raw_msg.get("id", "")
    snippet = raw_msg.get("snippet", "")
    payload = raw_msg.get("payload", {})
    headers = payload.get("headers", [])

    def _header(name: str) -> str:
        """Read a Gmail message header by name.

        Args:
            name: Header name to find.

        Returns:
            Header value, or an empty string.
        """
        for h in headers:
            if h.get("name", "").lower() == name.lower():
                return h.get("value", "")
        return ""

    subject_raw = _header("Subject")
    try:
        parts = decode_header(subject_raw)
        subject = "".join(
            p.decode(enc or "utf-8", errors="ignore") if isinstance(p, bytes) else p
            for p, enc in parts
        )
    except Exception:
        subject = subject_raw

    mime_type = payload.get("mimeType", "")
    body = ""
    if mime_type.startswith("multipart/"):
        for part in payload.get("parts", []):
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data", "")
                if data:
                    body = urlsafe_b64decode(data).decode("utf-8", errors="ignore")
                    break
    elif mime_type == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            body = urlsafe_b64decode(data).decode("utf-8", errors="ignore")

    label_ids = raw_msg.get("labelIds", [])
    has_attachments = any(p.get("filename") for p in payload.get("parts", []))

    return EmailMessage(
        msg_id=msg_id,
        thread_id=raw_msg.get("threadId", ""),
        subject=subject,
        sender=_header("From"),
        recipients=_header("To"),
        body=body,
        snippet=snippet,
        has_attachments=has_attachments,
        date=_header("Date"),
        star="STARRED" in label_ids,
        label=",".join(label_ids),
    )


# ---------------------------------------------------------------------------
# Service factory
# ---------------------------------------------------------------------------

def _build_service(token_data: dict) -> Any:
    """Build an authenticated Gmail API client.

    Args:
        token_data: OAuth token data injected by the orchestrator.

    Returns:
        Gmail API service object.
    """
    creds = Credentials(
        token=token_data.get("access_token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=["https://mail.google.com"],
    )
    return build("gmail", "v1", http=authorized_http(creds), cache_discovery=False)


# ---------------------------------------------------------------------------
# Core Gmail API class
# ---------------------------------------------------------------------------

_MAX_PAGINATION_CAP = 500  # hard upper limit across all pages
_CURSOR_TTL = 3600  # seconds; cursor expires after 1 hour of inactivity


class _GmailAPI:
    # ------------------------------------------------------------------
    # Pagination cursor helpers (stored in Django cache keyed by user_id)
    # ------------------------------------------------------------------

    def _save_cursor(self, user_id: str, query: str, page_token: str) -> None:
        """Save a pagination cursor for later Gmail page fetches.

        Args:
            user_id: Supabase UID of the requesting user.
            query: Gmail search query associated with the cursor.
            page_token: Gmail next page token.

        Returns:
            None.
        """
        cache.set(f"gmail_cursor:{user_id}", {"query": query, "page_token": page_token}, timeout=_CURSOR_TTL)

    def _load_cursor(self, user_id: str) -> Optional[dict]:
        """Load a saved Gmail pagination cursor.

        Args:
            user_id: Supabase UID of the requesting user.

        Returns:
            Cursor dictionary, or None.
        """
        return cache.get(f"gmail_cursor:{user_id}")

    def _clear_cursor(self, user_id: str) -> None:
        """Clear a saved Gmail pagination cursor.

        Args:
            user_id: Supabase UID of the requesting user.

        Returns:
            None.
        """
        cache.delete(f"gmail_cursor:{user_id}")

    def _update_cursor(self, user_id: Optional[str], query: str, emails: "EmailMessages") -> None:
        """Persist or clear cursor state from a Gmail response.

        Args:
            user_id: Optional Supabase UID of the requesting user.
            query: Gmail search query.
            emails: Email result containing an optional next page token.

        Returns:
            None.
        """
        if not user_id:
            return
        if emails.next_page_token:
            self._save_cursor(user_id, query, emails.next_page_token)
        else:
            self._clear_cursor(user_id)

    def _fetch_messages(self, service, query: str, max_results: int, initial_page_token: Optional[str] = None) -> EmailMessages:
        """Fetch and parse Gmail messages for a query.

        Args:
            service: Gmail API service object.
            query: Gmail search query.
            max_results: Maximum messages to fetch.
            initial_page_token: Optional Gmail page token.

        Returns:
            Parsed email messages with optional next page token.
        """
        max_results = max(1, min(max_results, _MAX_PAGINATION_CAP))
        logger.info("gmail fetch start query=%s max_results=%d", query, max_results)

        message_ids: List[dict] = []
        page_token: Optional[str] = initial_page_token
        # Page size per request: Gmail caps at 500; fetch in batches of 100 to stay responsive.
        page_size = min(max_results, 100)

        while len(message_ids) < max_results:
            kwargs: dict = {"userId": "me", "q": query, "maxResults": page_size}
            if page_token:
                kwargs["pageToken"] = page_token
            resp = service.users().messages().list(**kwargs).execute()
            batch = resp.get("messages", [])
            message_ids.extend(batch)
            page_token = resp.get("nextPageToken")
            if not page_token or not batch:
                break

        message_ids = message_ids[:max_results]
        logger.info("gmail list complete query=%s total_ids=%d", query, len(message_ids))

        parsed = []
        for m in message_ids:
            full = service.users().messages().get(
                userId="me", id=m["id"], format="full"
            ).execute()
            parsed.append(_parse_gmail_message(full))

        logger.info("gmail fetch complete query=%s parsed_messages=%d", query, len(parsed))
        return EmailMessages(
            count=len(parsed),
            messages=parsed,
            next_page_token=page_token,
        )

    def _fetch_drafts(self, service, max_results: int) -> EmailMessages:
        """Fetch and parse Gmail drafts.

        Args:
            service: Gmail API service object.
            max_results: Maximum drafts to fetch.

        Returns:
            Parsed draft messages with optional next page token.
        """
        resp = service.users().drafts().list(userId="me", maxResults=max_results).execute()
        parsed = []
        for d in resp.get("drafts", []):
            draft = service.users().drafts().get(userId="me", id=d["id"]).execute()
            parsed.append(_parse_gmail_message(draft["message"]))
        return EmailMessages(
            count=len(parsed),
            messages=parsed,
            next_page_token=resp.get("nextPageToken"),
        )

    def _date_q(self, hours_ago: Optional[int]) -> str:
        """Build an optional Gmail recency query fragment.

        Args:
            hours_ago: Optional recency window in hours.

        Returns:
            Gmail query fragment.
        """
        return "" if hours_ago is None else f" newer_than:{hours_ago}h"

    def _result(self, emails: EmailMessages) -> dict:
        """Wrap parsed email messages in the public tool response shape.

        Args:
            emails: Parsed email messages.

        Returns:
            Tool response dictionary.
        """
        return {
            "emails": emails.model_dump(),
        }

    async def search_emails(
        self,
        token_data: dict,
        keywords: List[str],
        max_results: int = 50,
        hours_ago: Optional[int] = None,
        user_id: Optional[str] = None,
    ) -> dict:
        """Search Gmail messages by keyword.

        Args:
            token_data: OAuth token data injected by the orchestrator.
            keywords: Search terms OR-combined in the Gmail query.
            max_results: Maximum messages to return.
            hours_ago: Optional recency window in hours.
            user_id: Optional Supabase UID for pagination cursor storage.

        Returns:
            Tool response containing parsed emails.
        """
        logger.info(
            "gmail.search_emails start keywords=%s max_results=%d hours_ago=%s",
            keywords,
            max_results,
            hours_ago,
        )
        service = _build_service(token_data)
        kq = " OR ".join(f'"{kw}"' for kw in keywords)
        query = f"({kq}){self._date_q(hours_ago)}"
        emails = await asyncio.to_thread(
            lambda: self._fetch_messages(service, query, max_results)
        )
        logger.info("gmail.search_emails complete count=%d", emails.count)
        self._update_cursor(user_id, query, emails)
        return self._result(emails)

    async def get_unread_emails(
        self,
        token_data: dict,
        max_results: int = 50,
        hours_ago: Optional[int] = None,
        user_id: Optional[str] = None,
    ) -> dict:
        """Fetch unread primary inbox emails.

        Args:
            token_data: OAuth token data injected by the orchestrator.
            max_results: Maximum messages to return.
            hours_ago: Optional recency window in hours.
            user_id: Optional Supabase UID for pagination cursor storage.

        Returns:
            Tool response containing parsed emails.
        """
        logger.info(
            "gmail.get_unread_emails start max_results=%d hours_ago=%s",
            max_results,
            hours_ago,
        )
        service = _build_service(token_data)
        query = f"in:inbox is:unread category:primary{self._date_q(hours_ago)}"
        emails = await asyncio.to_thread(
            lambda: self._fetch_messages(service, query, max_results)
        )
        logger.info("gmail.get_unread_emails complete count=%d", emails.count)
        self._update_cursor(user_id, query, emails)
        return self._result(emails)

    async def get_sent_emails(
        self,
        token_data: dict,
        max_results: int = 50,
        hours_ago: Optional[int] = None,
        user_id: Optional[str] = None,
    ) -> dict:
        """Fetch sent Gmail messages.

        Args:
            token_data: OAuth token data injected by the orchestrator.
            max_results: Maximum messages to return.
            hours_ago: Optional recency window in hours.
            user_id: Optional Supabase UID for pagination cursor storage.

        Returns:
            Tool response containing parsed emails.
        """
        logger.info(
            "gmail.get_sent_emails start max_results=%d hours_ago=%s",
            max_results,
            hours_ago,
        )
        service = _build_service(token_data)
        query = f"in:sent{self._date_q(hours_ago)}"
        emails = await asyncio.to_thread(
            lambda: self._fetch_messages(service, query, max_results)
        )
        logger.info("gmail.get_sent_emails complete count=%d", emails.count)
        self._update_cursor(user_id, query, emails)
        return self._result(emails)

    async def get_starred_emails(
        self,
        token_data: dict,
        max_results: int = 50,
        hours_ago: Optional[int] = None,
        user_id: Optional[str] = None,
    ) -> dict:
        """Fetch starred Gmail messages.

        Args:
            token_data: OAuth token data injected by the orchestrator.
            max_results: Maximum messages to return.
            hours_ago: Optional recency window in hours.
            user_id: Optional Supabase UID for pagination cursor storage.

        Returns:
            Tool response containing parsed emails.
        """
        logger.info(
            "gmail.get_starred_emails start max_results=%d hours_ago=%s",
            max_results,
            hours_ago,
        )
        service = _build_service(token_data)
        query = f"is:starred{self._date_q(hours_ago)}"
        emails = await asyncio.to_thread(
            lambda: self._fetch_messages(service, query, max_results)
        )
        logger.info("gmail.get_starred_emails complete count=%d", emails.count)
        self._update_cursor(user_id, query, emails)
        return self._result(emails)

    async def get_label_emails(
        self,
        token_data: dict,
        label: str,
        max_results: int = 50,
        hours_ago: Optional[int] = None,
        user_id: Optional[str] = None,
    ) -> dict:
        """Fetch Gmail messages with a specific label.

        Args:
            token_data: OAuth token data injected by the orchestrator.
            label: Gmail label query value.
            max_results: Maximum messages to return.
            hours_ago: Optional recency window in hours.
            user_id: Optional Supabase UID for pagination cursor storage.

        Returns:
            Tool response containing parsed emails.
        """
        logger.info(
            "gmail.get_label_emails start label=%s max_results=%d hours_ago=%s",
            label,
            max_results,
            hours_ago,
        )
        service = _build_service(token_data)
        query = f"label:{label}{self._date_q(hours_ago)}"
        emails = await asyncio.to_thread(
            lambda: self._fetch_messages(service, query, max_results)
        )
        logger.info("gmail.get_label_emails complete count=%d", emails.count)
        self._update_cursor(user_id, query, emails)
        return self._result(emails)

    async def get_next_page(
        self,
        token_data: dict,
        user_id: str,
        max_results: int = 50,
    ) -> dict:
        """Fetch the next page for the user's last Gmail query.

        Args:
            token_data: OAuth token data injected by the orchestrator.
            user_id: Supabase UID used to load the saved cursor.
            max_results: Maximum messages to return.

        Returns:
            Tool response containing parsed emails.
        """
        cursor = self._load_cursor(user_id)
        if not cursor:
            logger.info("gmail.get_next_page no cursor found for user_id=%s", user_id)
            return self._result(EmailMessages(count=0, messages=[], next_page_token=None))
        logger.info(
            "gmail.get_next_page user_id=%s query=%s max_results=%d",
            user_id,
            cursor["query"],
            max_results,
        )
        service = _build_service(token_data)
        emails = await asyncio.to_thread(
            lambda: self._fetch_messages(
                service, cursor["query"], max_results, initial_page_token=cursor["page_token"]
            )
        )
        logger.info("gmail.get_next_page complete count=%d", emails.count)
        self._update_cursor(user_id, cursor["query"], emails)
        return self._result(emails)

    async def get_drafts(self, token_data: dict, max_results: int = 50) -> dict:
        """Fetch Gmail draft messages.

        Args:
            token_data: OAuth token data injected by the orchestrator.
            max_results: Maximum drafts to return.

        Returns:
            Tool response containing parsed draft emails.
        """
        logger.info(
            "gmail.get_drafts start max_results=%d",
            max_results,
        )
        service = _build_service(token_data)
        emails = await asyncio.to_thread(lambda: self._fetch_drafts(service, max_results))
        logger.info(
            "gmail.get_drafts complete count=%d",
            emails.count,
        )
        return self._result(emails)

    async def send_email(
        self,
        token_data: dict,
        to: List[str],
        subject: str,
        body: str,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        reply_to: Optional[str] = None,
        thread_id: Optional[str] = None,
    ) -> dict:
        """Send a Gmail message.

        Args:
            token_data: OAuth token data injected by the orchestrator.
            to: Recipient email addresses.
            subject: Email subject.
            body: Email body.
            cc: Optional CC recipients.
            bcc: Optional BCC recipients.
            reply_to: RFC 2822 Message-ID of the email being replied to (sets
                In-Reply-To / References headers). Use gmail.reply_email instead
                for full in-thread replies.
            thread_id: Gmail thread ID to place this message in an existing thread.

        Returns:
            Send status and Gmail message ID.
        """
        service = _build_service(token_data)
        msg = MIMEText(body)
        msg["To"] = ", ".join(to)
        if cc:
            msg["Cc"] = ", ".join(cc)
        if bcc:
            msg["Bcc"] = ", ".join(bcc)
        msg["Subject"] = subject
        if reply_to:
            msg["In-Reply-To"] = reply_to
            msg["References"] = reply_to
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        send_args: dict = {"raw": raw}
        if thread_id:
            send_args["threadId"] = thread_id
        resp = await asyncio.to_thread(
            lambda: service.users().messages().send(userId="me", body=send_args).execute()
        )
        return {
            "status": "success",
            "message_id": resp.get("id"),
        }

    async def reply_email(
        self,
        token_data: dict,
        msg_id: str,
        body: str,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
    ) -> dict:
        """Reply to a Gmail message in-thread.

        Fetches the original message to extract its thread ID and RFC 2822
        Message-ID, then sends the reply with correct In-Reply-To / References
        headers and places it in the same thread.

        Args:
            token_data: OAuth token data injected by the orchestrator.
            msg_id: Gmail message ID of the email to reply to.
            body: Plain-text reply body.
            cc: Optional CC recipients.
            bcc: Optional BCC recipients.

        Returns:
            Send status, new message ID, and thread ID.
        """
        def _reply():
            service = _build_service(token_data)
            original = service.users().messages().get(
                userId="me", id=msg_id, format="full"
            ).execute()
            thread_id = original.get("threadId", "")
            raw_headers = original.get("payload", {}).get("headers", [])
            hdrs = {h["name"].lower(): h["value"] for h in raw_headers}

            rfc_message_id = hdrs.get("message-id", "")
            original_subject = hdrs.get("subject", "")
            original_from = hdrs.get("from", "")
            prior_references = hdrs.get("references", "")

            subject = (
                original_subject
                if original_subject.lower().startswith("re:")
                else f"Re: {original_subject}"
            )
            references = (
                f"{prior_references} {rfc_message_id}".strip()
                if prior_references
                else rfc_message_id
            )

            reply_msg = MIMEText(body)
            reply_msg["To"] = original_from
            reply_msg["Subject"] = subject
            if rfc_message_id:
                reply_msg["In-Reply-To"] = rfc_message_id
                reply_msg["References"] = references
            if cc:
                reply_msg["Cc"] = ", ".join(cc)
            if bcc:
                reply_msg["Bcc"] = ", ".join(bcc)

            raw = base64.urlsafe_b64encode(reply_msg.as_bytes()).decode()
            resp = service.users().messages().send(
                userId="me", body={"raw": raw, "threadId": thread_id}
            ).execute()
            return {
                "status": "success",
                "message_id": resp.get("id"),
                "thread_id": thread_id,
            }

        result = await asyncio.to_thread(_reply)
        logger.info(
            "gmail.reply_email original_msg_id=%s new_msg_id=%s thread_id=%s",
            msg_id,
            result.get("message_id"),
            result.get("thread_id"),
        )
        return result

    async def send_draft(self, token_data: dict, draft_id: str) -> dict:
        """Send an existing Gmail draft.

        Args:
            token_data: OAuth token data injected by the orchestrator.
            draft_id: Gmail draft ID to send.

        Returns:
            Send status and Gmail message ID.
        """
        service = _build_service(token_data)
        resp = await asyncio.to_thread(
            lambda: service.users().drafts().send(userId="me", body={"id": draft_id}).execute()
        )
        return {
            "status": "success",
            "message_id": resp.get("id"),
        }

    async def get_attachment(self, token_data: dict, msg_id: str, attachment_id: str) -> dict:
        """Fetch Gmail attachment content.

        Args:
            token_data: OAuth token data injected by the orchestrator.
            msg_id: Gmail message ID.
            attachment_id: Gmail attachment ID.

        Returns:
            Attachment metadata and decoded content.
        """
        def _fetch():
            """Fetch attachment data from the blocking Gmail API client.

            Returns:
                Raw attachment response.
            """
            service = _build_service(token_data)
            return service.users().messages().attachments().get(
                userId="me", messageId=msg_id, id=attachment_id
            ).execute()

        data = await asyncio.to_thread(_fetch)
        raw_b64 = data.get("data", "")
        size = data.get("size", 0)

        # Attempt UTF-8 decode so the LLM can read text attachments directly.
        try:
            content = urlsafe_b64decode(raw_b64).decode("utf-8")
            encoding = "utf-8"
        except (UnicodeDecodeError, Exception):
            content = raw_b64  # return raw base64 for binary files
            encoding = "base64"

        return {
            "msg_id": msg_id,
            "attachment_id": attachment_id,
            "size_bytes": size,
            "encoding": encoding,
            "content": content,
        }

    async def trash_email(self, token_data: dict, msg_id: str) -> dict:
        """Move a Gmail message to Trash.

        Args:
            token_data: OAuth token data injected by the orchestrator.
            msg_id: Gmail message ID.

        Returns:
            Trash confirmation.
        """
        def _trash():
            """Trash a message through the blocking Gmail API client.

            Returns:
                Raw Gmail API response.
            """
            service = _build_service(token_data)
            return service.users().messages().trash(userId="me", id=msg_id).execute()

        await asyncio.to_thread(_trash)
        logger.info("gmail.trash_email msg_id=%s", msg_id)
        return {"status": "trashed", "msg_id": msg_id}

    async def mark_read(self, token_data: dict, msg_id: str) -> dict:
        """Mark a Gmail message as read.

        Args:
            token_data: OAuth token data injected by the orchestrator.
            msg_id: Gmail message ID.

        Returns:
            Read-status confirmation.
        """
        def _modify():
            """Remove the unread label through the blocking Gmail API client.

            Returns:
                Raw Gmail API response.
            """
            service = _build_service(token_data)
            return service.users().messages().modify(
                userId="me", id=msg_id, body={"removeLabelIds": ["UNREAD"]}
            ).execute()

        await asyncio.to_thread(_modify)
        logger.info("gmail.mark_read msg_id=%s", msg_id)
        return {"status": "marked_read", "msg_id": msg_id}

    async def mark_unread(self, token_data: dict, msg_id: str) -> dict:
        """Mark a Gmail message as unread.

        Args:
            token_data: OAuth token data injected by the orchestrator.
            msg_id: Gmail message ID.

        Returns:
            Unread-status confirmation.
        """
        def _modify():
            """Add the unread label through the blocking Gmail API client.

            Returns:
                Raw Gmail API response.
            """
            service = _build_service(token_data)
            return service.users().messages().modify(
                userId="me", id=msg_id, body={"addLabelIds": ["UNREAD"]}
            ).execute()

        await asyncio.to_thread(_modify)
        logger.info("gmail.mark_unread msg_id=%s", msg_id)
        return {"status": "marked_unread", "msg_id": msg_id}

    def _resolve_label_id(self, service, label_name: str) -> str:
        """Resolve a Gmail label name to an ID.

        Args:
            service: Gmail API service object.
            label_name: Case-insensitive label name.

        Returns:
            Gmail label ID.
        """
        resp = service.users().labels().list(userId="me").execute()
        for lbl in resp.get("labels", []):
            if lbl.get("name", "").lower() == label_name.lower():
                return lbl["id"]
        raise ValueError(f"Gmail label not found: {label_name!r}")

    async def add_label(self, token_data: dict, msg_id: str, label_name: str) -> dict:
        """Apply a Gmail label to a message.

        Args:
            token_data: OAuth token data injected by the orchestrator.
            msg_id: Gmail message ID.
            label_name: Label name to apply.

        Returns:
            Label-add confirmation.
        """
        def _add():
            """Apply a label through the blocking Gmail API client.

            Returns:
                Raw Gmail API response.
            """
            service = _build_service(token_data)
            label_id = self._resolve_label_id(service, label_name)
            return service.users().messages().modify(
                userId="me", id=msg_id, body={"addLabelIds": [label_id]}
            ).execute()

        await asyncio.to_thread(_add)
        logger.info("gmail.add_label msg_id=%s label=%s", msg_id, label_name)
        return {"status": "label_added", "msg_id": msg_id, "label": label_name}

    async def remove_label(self, token_data: dict, msg_id: str, label_name: str) -> dict:
        """Remove a Gmail label from a message.

        Args:
            token_data: OAuth token data injected by the orchestrator.
            msg_id: Gmail message ID.
            label_name: Label name to remove.

        Returns:
            Label-remove confirmation.
        """
        def _remove():
            """Remove a label through the blocking Gmail API client.

            Returns:
                Raw Gmail API response.
            """
            service = _build_service(token_data)
            label_id = self._resolve_label_id(service, label_name)
            return service.users().messages().modify(
                userId="me", id=msg_id, body={"removeLabelIds": [label_id]}
            ).execute()

        await asyncio.to_thread(_remove)
        logger.info("gmail.remove_label msg_id=%s label=%s", msg_id, label_name)
        return {"status": "label_removed", "msg_id": msg_id, "label": label_name}

    async def create_draft(
        self,
        token_data: dict,
        to: List[str],
        subject: str,
        body: str,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
    ) -> dict:
        """Create a Gmail draft.

        Args:
            token_data: OAuth token data injected by the orchestrator.
            to: Recipient email addresses.
            subject: Draft subject.
            body: Draft body.
            cc: Optional CC recipients.
            bcc: Optional BCC recipients.

        Returns:
            Draft creation status and draft ID.
        """
        def _create():
            """Create a draft through the blocking Gmail API client.

            Returns:
                Gmail draft ID.
            """
            service = _build_service(token_data)
            msg = MIMEText(body)
            msg["To"] = ", ".join(to)
            msg["Subject"] = subject
            if cc:
                msg["Cc"] = ", ".join(cc)
            if bcc:
                msg["Bcc"] = ", ".join(bcc)
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            resp = service.users().drafts().create(
                userId="me", body={"message": {"raw": raw}}
            ).execute()
            return resp.get("id", "")

        draft_id = await asyncio.to_thread(_create)
        logger.info("gmail.create_draft draft_id=%s subject=%r", draft_id, subject)
        return {"status": "draft_created", "draft_id": draft_id}


_gmail = _GmailAPI()

# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

register(ToolDef(
    name="gmail.search_emails",
    display_name="Search Emails",
    description="Search Gmail for emails whose subject or body matches the given keywords, optionally filtered by recency.",
    params_schema={
        "keywords": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Keywords to search for (OR-combined).",
            "required": True,
        },
        "max_results": {"type": "integer", "default": 50, "required": False},
        "hours_ago": {
            "type": "integer",
            "description": "Only include emails newer than this many hours.",
            "required": False,
        },
    },
    fn=_gmail.search_emails,
    requires_creds=True,
    requires_user_id=True,
    plugin_id="gmail",
))

register(ToolDef(
    name="gmail.get_unread_emails",
    display_name="Get Unread Emails",
    description="Fetch unread emails from the Gmail inbox.",
    params_schema={
        "max_results": {"type": "integer", "default": 50, "required": False},
        "hours_ago": {
            "type": "integer",
            "description": "Only include emails newer than this many hours.",
            "required": False,
        },
    },
    fn=_gmail.get_unread_emails,
    requires_creds=True,
    requires_user_id=True,
    plugin_id="gmail",
))

register(ToolDef(
    name="gmail.get_sent_emails",
    display_name="Get Sent Emails",
    description="Fetch sent emails from Gmail.",
    params_schema={
        "max_results": {"type": "integer", "default": 50, "required": False},
        "hours_ago": {
            "type": "integer",
            "description": "Only include emails newer than this many hours.",
            "required": False,
        },
    },
    fn=_gmail.get_sent_emails,
    requires_creds=True,
    requires_user_id=True,
    plugin_id="gmail",
))

register(ToolDef(
    name="gmail.get_starred_emails",
    display_name="Get Starred Emails",
    description="Fetch starred emails from Gmail.",
    params_schema={
        "max_results": {"type": "integer", "default": 50, "required": False},
        "hours_ago": {
            "type": "integer",
            "description": "Only include emails newer than this many hours.",
            "required": False,
        },
    },
    fn=_gmail.get_starred_emails,
    requires_creds=True,
    requires_user_id=True,
    plugin_id="gmail",
))

register(ToolDef(
    name="gmail.get_label_emails",
    display_name="Get Emails by Label",
    description="Fetch emails for a specific Gmail label.",
    params_schema={
        "label": {"type": "string", "description": "Gmail label name, e.g. 'Work'.", "required": True},
        "max_results": {"type": "integer", "default": 50, "required": False},
        "hours_ago": {
            "type": "integer",
            "description": "Only include emails newer than this many hours.",
            "required": False,
        },
    },
    fn=_gmail.get_label_emails,
    requires_creds=True,
    requires_user_id=True,
    plugin_id="gmail",
))

register(ToolDef(
    name="gmail.get_next_page",
    display_name="Get Next Email Page",
    description=(
        "Fetch the next page of emails from the most recent Gmail query in this session. "
        "Use this when the user asks to see more emails after a prior fetch - "
        "e.g. 'show me more', 'next page', 'load more emails'."
    ),
    params_schema={
        "max_results": {"type": "integer", "default": 50, "required": False},
    },
    fn=_gmail.get_next_page,
    requires_creds=True,
    requires_user_id=True,
    plugin_id="gmail",
))

register(ToolDef(
    name="gmail.get_drafts",
    display_name="Get Drafts",
    description="Fetch email drafts from Gmail.",
    params_schema={
        "max_results": {"type": "integer", "default": 50, "required": False},
    },
    fn=_gmail.get_drafts,
    requires_creds=True,
    plugin_id="gmail",
))

register(ToolDef(
    name="gmail.send_email",
    display_name="Send Email",
    description="Send a new plain-text email via Gmail.",
    params_schema={
        "to": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Recipient email addresses.",
            "required": True,
        },
        "subject": {"type": "string", "required": True},
        "body": {"type": "string", "description": "Plain-text email body.", "required": True},
        "cc": {
            "type": "array",
            "items": {"type": "string"},
            "required": False,
        },
        "bcc": {
            "type": "array",
            "items": {"type": "string"},
            "required": False,
        },
        "reply_to": {
            "type": "string",
            "description": "Message ID to reply to (sets In-Reply-To / References headers).",
            "required": False,
        },
    },
    fn=_gmail.send_email,
    requires_creds=True,
    plugin_id="gmail",
    requires_confirmation=True,
))

register(ToolDef(
    name="gmail.send_draft",
    display_name="Send Draft",
    description="Send an existing Gmail draft by its draft ID.",
    params_schema={
        "draft_id": {"type": "string", "description": "The ID of the draft to send.", "required": True},
    },
    fn=_gmail.send_draft,
    requires_creds=True,
    plugin_id="gmail",
    requires_confirmation=True,
))

register(ToolDef(
    name="gmail.get_attachment",
    display_name="Get Email Attachment",
    description=(
        "Fetch the content of an email attachment. "
        "Use this when the user asks to read, summarise, or act on an attachment. "
        "The msg_id and attachment_id come from a prior gmail fetch step."
    ),
    params_schema={
        "msg_id": {"type": "string", "description": "The Gmail message ID that contains the attachment.", "required": True},
        "attachment_id": {"type": "string", "description": "The attachment ID from the message payload.", "required": True},
    },
    fn=_gmail.get_attachment,
    requires_creds=True,
    plugin_id="gmail",
    requires_confirmation=False,
))

register(ToolDef(
    name="gmail.trash_email",
    display_name="Trash Email",
    description="Move a Gmail message to Trash by its message ID.",
    params_schema={
        "msg_id": {"type": "string", "description": "The Gmail message ID to trash.", "required": True},
    },
    fn=_gmail.trash_email,
    requires_creds=True,
    plugin_id="gmail",
    requires_confirmation=True,
))

register(ToolDef(
    name="gmail.mark_read",
    display_name="Mark as Read",
    description="Mark a Gmail message as read (removes the UNREAD label).",
    params_schema={
        "msg_id": {"type": "string", "description": "The Gmail message ID to mark as read.", "required": True},
    },
    fn=_gmail.mark_read,
    requires_creds=True,
    plugin_id="gmail",
    requires_confirmation=False,
))

register(ToolDef(
    name="gmail.mark_unread",
    display_name="Mark as Unread",
    description="Mark a Gmail message as unread (adds the UNREAD label).",
    params_schema={
        "msg_id": {"type": "string", "description": "The Gmail message ID to mark as unread.", "required": True},
    },
    fn=_gmail.mark_unread,
    requires_creds=True,
    plugin_id="gmail",
    requires_confirmation=False,
))

register(ToolDef(
    name="gmail.add_label",
    display_name="Add Label",
    description="Apply a Gmail label to a message by label name.",
    params_schema={
        "msg_id": {"type": "string", "description": "The Gmail message ID.", "required": True},
        "label_name": {"type": "string", "description": "The Gmail label name to apply, e.g. 'Work'.", "required": True},
    },
    fn=_gmail.add_label,
    requires_creds=True,
    plugin_id="gmail",
    requires_confirmation=False,
))

register(ToolDef(
    name="gmail.remove_label",
    display_name="Remove Label",
    description="Remove a Gmail label from a message by label name.",
    params_schema={
        "msg_id": {"type": "string", "description": "The Gmail message ID.", "required": True},
        "label_name": {"type": "string", "description": "The Gmail label name to remove, e.g. 'Work'.", "required": True},
    },
    fn=_gmail.remove_label,
    requires_creds=True,
    plugin_id="gmail",
    requires_confirmation=False,
))

register(ToolDef(
    name="gmail.create_draft",
    display_name="Create Draft",
    description="Save a composed email as a Gmail draft without sending it.",
    params_schema={
        "to": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Recipient email addresses.",
            "required": True,
        },
        "subject": {"type": "string", "required": True},
        "body": {"type": "string", "description": "Plain-text email body.", "required": True},
        "cc": {
            "type": "array",
            "items": {"type": "string"},
            "required": False,
        },
        "bcc": {
            "type": "array",
            "items": {"type": "string"},
            "required": False,
        },
    },
    fn=_gmail.create_draft,
    requires_creds=True,
    plugin_id="gmail",
    requires_confirmation=False,
))

register(ToolDef(
    name="gmail.reply_email",
    display_name="Reply to Email",
    description=(
        "Reply to an existing Gmail message in-thread. "
        "Automatically sets In-Reply-To and References headers and places the reply "
        "in the correct Gmail thread. Use this instead of gmail.send_email when replying. "
        "The msg_id comes from a prior gmail fetch or search step."
    ),
    params_schema={
        "msg_id": {
            "type": "string",
            "description": "Gmail message ID of the email to reply to.",
            "required": True,
        },
        "body": {
            "type": "string",
            "description": "Plain-text reply body.",
            "required": True,
        },
        "cc": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional CC recipients.",
            "required": False,
        },
        "bcc": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional BCC recipients.",
            "required": False,
        },
    },
    fn=_gmail.reply_email,
    requires_creds=True,
    plugin_id="gmail",
    requires_confirmation=True,
))
