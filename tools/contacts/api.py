"""
Contacts tools — backed by the existing Contact / ContactConnection DB models.
No external credentials needed; all data lives in the Aiva database.
"""
import logging
from typing import Any, Dict, List, Optional

from asgiref.sync import sync_to_async

from tools.registry import ToolDef, register

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DB helpers (sync, wrapped with sync_to_async)
# ---------------------------------------------------------------------------

def _get_user(supabase_uid: str):
    """Load a local user by Supabase UID.

    Args:
        supabase_uid: Supabase Auth user ID.

    Returns:
        Matching Django user.
    """
    from django.contrib.auth import get_user_model
    User = get_user_model()
    return User.objects.get(supabase_uid=supabase_uid)


def _contact_to_dict(contact) -> Dict[str, Any]:
    """Serialize a contact for tool output.

    Args:
        contact: Contact model instance.

    Returns:
        Contact dictionary with connection data.
    """
    connections = list(
        contact.connections.values("service", "alias", "external_id", "metadata")
    )
    return {
        "id": contact.pk,
        "first_name": contact.first_name,
        "last_name": contact.last_name or "",
        "alias": contact.alias or "",
        "connections": connections,
    }


@sync_to_async
def _search_contacts(user_id: str, query: str, limit: int) -> List[Dict[str, Any]]:
    """Search contacts in the database.

    Args:
        user_id: Supabase UID of the contact owner.
        query: Search text.
        limit: Maximum number of contacts to return.

    Returns:
        List of serialized contacts.
    """
    from django.db.models import Q
    from contacts.models import Contact

    user = _get_user(user_id)
    qs = Contact.objects.filter(user=user).prefetch_related("connections")
    if query:
        qs = qs.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(alias__icontains=query)
            | Q(connections__external_id__icontains=query)
        ).distinct()
    return [_contact_to_dict(c) for c in qs[:limit]]


@sync_to_async
def _create_contact(
    user_id: str,
    first_name: str,
    last_name: Optional[str],
    alias: Optional[str],
    email: Optional[str],
) -> Dict[str, Any]:
    """Create a contact in the database.

    Args:
        user_id: Supabase UID of the contact owner.
        first_name: Contact first name.
        last_name: Optional contact last name.
        alias: Optional contact alias.
        email: Optional email connection.

    Returns:
        Serialized contact.
    """
    from contacts.models import Contact, ContactConnection

    user = _get_user(user_id)
    contact = Contact.objects.create(
        user=user,
        first_name=first_name,
        last_name=last_name or "",
        alias=alias or "",
    )
    if email:
        ContactConnection.objects.create(
            contact=contact,
            service="email",
            external_id=email,
        )
    contact.refresh_from_db()
    return _contact_to_dict(contact)


@sync_to_async
def _delete_contact(user_id: str, contact_id: int) -> Dict[str, Any]:
    """Delete a contact from the database.

    Args:
        user_id: Supabase UID of the contact owner.
        contact_id: Contact primary key.

    Returns:
        Serialized contact that was deleted.
    """
    from contacts.models import Contact

    user = _get_user(user_id)
    contact = Contact.objects.get(pk=contact_id, user=user)
    info = _contact_to_dict(contact)
    contact.delete()
    return info


@sync_to_async
def _update_contact(
    user_id: str,
    contact_id: int,
    first_name: Optional[str],
    last_name: Optional[str],
    alias: Optional[str],
    email: Optional[str],
) -> Dict[str, Any]:
    """Update a contact in the database.

    Args:
        user_id: Supabase UID of the contact owner.
        contact_id: Contact primary key.
        first_name: Optional new first name.
        last_name: Optional new last name.
        alias: Optional new alias.
        email: Optional new email connection.

    Returns:
        Serialized updated contact.
    """
    from contacts.models import Contact, ContactConnection

    user = _get_user(user_id)
    contact = Contact.objects.prefetch_related("connections").get(pk=contact_id, user=user)

    if first_name is not None:
        contact.first_name = first_name
    if last_name is not None:
        contact.last_name = last_name
    if alias is not None:
        contact.alias = alias
    contact.save()

    if email is not None:
        ContactConnection.objects.update_or_create(
            contact=contact,
            service="email",
            defaults={"external_id": email},
        )

    contact.refresh_from_db()
    return _contact_to_dict(contact)


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------

async def contacts_delete(user_id: str, contact_id: int) -> Dict[str, Any]:
    """Delete a contact owned by the user.

    Args:
        user_id: Supabase UID of the contact owner.
        contact_id: Contact primary key.

    Returns:
        Deletion confirmation and deleted contact data.
    """
    contact = await _delete_contact(user_id, contact_id)
    logger.info("contacts.delete user_id=%s contact_id=%s", user_id, contact_id)
    return {"deleted": True, "contact": contact}


async def contacts_search(user_id: str, query: str = "", limit: int = 20) -> List[Dict[str, Any]]:
    """Search the user's contacts.

    Args:
        user_id: Supabase UID of the contact owner.
        query: Search text.
        limit: Maximum number of contacts to return.

    Returns:
        List of serialized contacts.
    """
    results = await _search_contacts(user_id, query, max(1, min(limit, 100)))
    logger.info("contacts.search user_id=%s query=%r returned=%d", user_id, query, len(results))
    return results


async def contacts_create(
    user_id: str,
    first_name: str,
    last_name: str = "",
    alias: str = "",
    email: str = "",
) -> Dict[str, Any]:
    """Create a new contact for the user.

    Args:
        user_id: Supabase UID of the contact owner.
        first_name: Contact first name.
        last_name: Optional contact last name.
        alias: Optional contact alias.
        email: Optional email address connection.

    Returns:
        Serialized new contact.
    """
    contact = await _create_contact(
        user_id,
        first_name=first_name,
        last_name=last_name or None,
        alias=alias or None,
        email=email or None,
    )
    logger.info("contacts.create user_id=%s contact_id=%s", user_id, contact["id"])
    return contact


async def contacts_update(
    user_id: str,
    contact_id: int,
    first_name: str = "",
    last_name: str = "",
    alias: str = "",
    email: str = "",
) -> Dict[str, Any]:
    """Update an existing contact.

    Args:
        user_id: Supabase UID of the contact owner.
        contact_id: Contact primary key.
        first_name: Optional new first name.
        last_name: Optional new last name.
        alias: Optional new alias.
        email: Optional new email address.

    Returns:
        Serialized updated contact.
    """
    contact = await _update_contact(
        user_id,
        contact_id=contact_id,
        first_name=first_name or None,
        last_name=last_name or None,
        alias=alias or None,
        email=email or None,
    )
    logger.info("contacts.update user_id=%s contact_id=%s", user_id, contact["id"])
    return contact


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

register(ToolDef(
    name="contacts.search",
    display_name="Search Contacts",
    description="Search the user's contacts by name, alias, or email address.",
    params_schema={
        "query": {"type": "string", "description": "Name, alias, or email fragment to search for. Empty string returns all contacts.", "required": True},
        "limit": {"type": "integer", "description": "Maximum number of contacts to return (default 20, max 100).", "required": False},
    },
    fn=contacts_search,
    requires_user_id=True,
))

register(ToolDef(
    name="contacts.create",
    display_name="Create Contact",
    description="Create a new contact for the user.",
    params_schema={
        "first_name": {"type": "string", "description": "Contact's first name.", "required": True},
        "last_name": {"type": "string", "description": "Contact's last name.", "required": False},
        "alias": {"type": "string", "description": "A nickname or alias.", "required": False},
        "email": {"type": "string", "description": "Contact's email address.", "required": False},
    },
    fn=contacts_create,
    requires_user_id=True,
))

register(ToolDef(
    name="contacts.update",
    display_name="Update Contact",
    description="Update an existing contact. Only provided (non-empty) fields are changed.",
    params_schema={
        "contact_id": {"type": "integer", "description": "ID of the contact to update.", "required": True},
        "first_name": {"type": "string", "description": "New first name (leave empty to keep current).", "required": False},
        "last_name": {"type": "string", "description": "New last name (leave empty to keep current).", "required": False},
        "alias": {"type": "string", "description": "New alias (leave empty to keep current).", "required": False},
        "email": {"type": "string", "description": "New email address (leave empty to keep current).", "required": False},
    },
    fn=contacts_update,
    requires_user_id=True,
))

register(ToolDef(
    name="contacts.delete",
    display_name="Delete Contact",
    description="Permanently delete a contact from the user's address book.",
    params_schema={
        "contact_id": {"type": "integer", "description": "ID of the contact to delete.", "required": True},
    },
    fn=contacts_delete,
    requires_user_id=True,
    requires_confirmation=True,
))

