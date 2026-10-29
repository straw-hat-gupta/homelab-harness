"""
Google People API tools - backed by the Google People API v1.
Credentials (token_data) are injected by the orchestrator via the google_contacts plugin.
"""
import asyncio
import logging
from typing import Any, Dict, List

from django.conf import settings
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from tools.google_http import authorized_http
from tools.registry import ToolDef, register

logger = logging.getLogger(__name__)

_PEOPLE_SCOPES = ["https://www.googleapis.com/auth/contacts.readonly"]
_PERSON_FIELDS = "names,emailAddresses,phoneNumbers"


def _build_service(token_data: dict):
    creds = Credentials(
        token=token_data["access_token"],
        refresh_token=token_data.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=_PEOPLE_SCOPES,
    )
    return build("people", "v1", http=authorized_http(creds), cache_discovery=False)


def _person_to_dict(person: dict) -> Dict[str, Any]:
    names = person.get("names", [])
    emails = person.get("emailAddresses", [])
    phones = person.get("phoneNumbers", [])
    first_name = names[0].get("givenName", "") if names else ""
    last_name = names[0].get("familyName", "") if names else ""
    return {
        "resource_name": person.get("resourceName", ""),
        "first_name": first_name,
        "last_name": last_name,
        "emails": [e.get("value", "") for e in emails],
        "phones": [p.get("value", "") for p in phones],
    }


def _fetch_all_connections(service) -> List[dict]:
    results = []
    page_token = None
    while True:
        resp = service.people().connections().list(
            resourceName="people/me",
            pageSize=1000,
            personFields=_PERSON_FIELDS,
            pageToken=page_token,
        ).execute()
        results.extend(resp.get("connections", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return results


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------

async def google_contacts_list(
    token_data: dict,
    max_results: int = 100,
) -> List[Dict[str, Any]]:
    """List the user's Google contacts.

    Args:
        token_data: OAuth token data injected by the orchestrator.
        max_results: Maximum number of contacts to return (default 100, max 1000).

    Returns:
        List of contacts with name, emails, and phone numbers.
    """
    def _fetch():
        service = _build_service(token_data)
        limit = max(1, min(max_results, 1000))
        results = []
        page_token = None
        while len(results) < limit:
            resp = service.people().connections().list(
                resourceName="people/me",
                pageSize=min(limit - len(results), 1000),
                personFields=_PERSON_FIELDS,
                pageToken=page_token,
            ).execute()
            results.extend(resp.get("connections", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return [_person_to_dict(p) for p in results[:limit]]

    contacts = await asyncio.to_thread(_fetch)
    logger.info("google_contacts.list returned=%d", len(contacts))
    return contacts


async def google_contacts_search(
    token_data: dict,
    query: str,
    max_results: int = 20,
) -> List[Dict[str, Any]]:
    """Search the user's Google contacts by name or email.

    Args:
        token_data: OAuth token data injected by the orchestrator.
        query: Name or email fragment to search for.
        max_results: Maximum number of contacts to return (default 20, max 30).

    Returns:
        List of matching contacts.
    """
    def _fetch():
        service = _build_service(token_data)
        # People API searchContacts max pageSize is 30
        resp = service.people().searchContacts(
            query=query,
            readMask=_PERSON_FIELDS,
            pageSize=max(1, min(max_results, 30)),
        ).execute()
        return [
            _person_to_dict(r["person"])
            for r in resp.get("results", [])
            if "person" in r
        ]

    contacts = await asyncio.to_thread(_fetch)
    logger.info("google_contacts.search query=%r returned=%d", query, len(contacts))
    return contacts


async def google_contacts_sync(
    token_data: dict,
    user_id: str,
) -> Dict[str, Any]:
    """Sync Google contacts into the Aiva contact database.

    Fetches all Google contacts and upserts them as Contact records with a Gmail
    ContactConnection. Contacts without an email address are skipped.

    Args:
        token_data: OAuth token data injected by the orchestrator.
        user_id: Supabase UID used to scope the upsert.

    Returns:
        Summary with created, updated, and skipped counts.
    """
    def _fetch_google():
        return _fetch_all_connections(_build_service(token_data))

    def _upsert(persons: List[dict]) -> Dict[str, int]:
        from django.contrib.auth import get_user_model
        from contacts.models import Contact, ContactConnection

        User = get_user_model()
        user = User.objects.get(supabase_uid=user_id)

        created = updated = skipped = 0

        for person in persons:
            info = _person_to_dict(person)
            if not info["emails"]:
                skipped += 1
                continue

            primary_email = info["emails"][0]

            existing_conn = (
                ContactConnection.objects.filter(
                    contact__user=user, service="Gmail", external_id=primary_email
                )
                .select_related("contact")
                .first()
            )

            if existing_conn:
                contact = existing_conn.contact
                changed = False
                if info["first_name"] and contact.first_name != info["first_name"]:
                    contact.first_name = info["first_name"]
                    changed = True
                if info["last_name"] and contact.last_name != info["last_name"]:
                    contact.last_name = info["last_name"]
                    changed = True
                if changed:
                    contact.save(update_fields=["first_name", "last_name"])
                updated += 1
            else:
                first_name = info["first_name"] or primary_email.split("@")[0]
                contact = Contact.objects.create(
                    user=user,
                    first_name=first_name,
                    last_name=info["last_name"] or "",
                )
                ContactConnection.objects.create(
                    contact=contact,
                    service="Gmail",
                    external_id=primary_email,
                )
                created += 1

        return {"created": created, "updated": updated, "skipped": skipped}

    persons = await asyncio.to_thread(_fetch_google)
    result = await asyncio.to_thread(_upsert, persons)
    logger.info(
        "google_contacts.sync user_id=%s fetched=%d created=%d updated=%d skipped=%d",
        user_id,
        len(persons),
        result["created"],
        result["updated"],
        result["skipped"],
    )
    return {"total_fetched": len(persons), **result}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

register(ToolDef(
    name="google_contacts.list",
    display_name="List Google Contacts",
    description="List the user's Google contacts including names, email addresses, and phone numbers.",
    params_schema={
        "max_results": {
            "type": "integer",
            "description": "Maximum number of contacts to return (default 100, max 1000).",
            "required": False,
        },
    },
    fn=google_contacts_list,
    requires_creds=True,
    plugin_id="google_contacts",
))

register(ToolDef(
    name="google_contacts.search",
    display_name="Search Google Contacts",
    description="Search the user's Google contacts by name or email address.",
    params_schema={
        "query": {
            "type": "string",
            "description": "Name or email fragment to search for.",
            "required": True,
        },
        "max_results": {
            "type": "integer",
            "description": "Maximum number of contacts to return (default 20, max 30).",
            "required": False,
        },
    },
    fn=google_contacts_search,
    requires_creds=True,
    plugin_id="google_contacts",
))

register(ToolDef(
    name="google_contacts.sync",
    display_name="Sync Google Contacts",
    description=(
        "Import all Google contacts into the Aiva contact database. "
        "Contacts are matched by email address - existing records are updated, "
        "new ones are created. Contacts without an email address are skipped."
    ),
    params_schema={},
    fn=google_contacts_sync,
    requires_creds=True,
    plugin_id="google_contacts",
    requires_user_id=True,
))
