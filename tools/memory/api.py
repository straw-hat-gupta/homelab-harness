"""
Memory tools — read/write the user's persistent UserMemory store.
Requires user_id injection (no OAuth credentials needed).
"""
import logging

from asgiref.sync import sync_to_async

from tools.registry import ToolDef, register

logger = logging.getLogger(__name__)


@sync_to_async
def _save(user_id: str, key: str, value: str) -> dict:
    from django.contrib.auth import get_user_model
    from agent.models import UserMemory
    User = get_user_model()
    user = User.objects.get(supabase_uid=user_id)
    obj, created = UserMemory.objects.update_or_create(
        user=user,
        key=key,
        defaults={"value": value, "source": UserMemory.SOURCE_AGENT},
    )
    action = "created" if created else "updated"
    logger.info("memory.save user_id=%s key=%r %s", user_id, key, action)
    return {"key": key, "value": value, "action": action}


@sync_to_async
def _delete(user_id: str, key: str) -> dict:
    from django.contrib.auth import get_user_model
    from agent.models import UserMemory
    User = get_user_model()
    user = User.objects.get(supabase_uid=user_id)
    deleted, _ = UserMemory.objects.filter(user=user, key=key).delete()
    logger.info("memory.delete user_id=%s key=%r deleted=%d", user_id, key, deleted)
    return {"key": key, "deleted": deleted > 0}


async def memory_save(key: str, value: str, user_id: str) -> dict:
    """Persist a key/value memory for the user."""
    return await _save(user_id, key, value)


async def memory_delete(key: str, user_id: str) -> dict:
    """Remove a memory entry by key."""
    return await _delete(user_id, key)


register(ToolDef(
    name="memory.save",
    display_name="Save Memory",
    description=(
        "Save or update a persistent memory about the user. "
        "Use this to remember facts, preferences, or context that should persist across conversations. "
        "Examples: user's name, location, preferences, ongoing goals, or anything the user asks you to remember."
    ),
    params_schema={
        "key": {
            "type": "string",
            "description": "Short identifier for the memory (e.g. 'user_name', 'home_city', 'preferred_language').",
            "required": True,
        },
        "value": {
            "type": "string",
            "description": "The value to store for this key.",
            "required": True,
        },
    },
    fn=memory_save,
    requires_confirmation=False,
    requires_user_id=True,
))

register(ToolDef(
    name="memory.delete",
    display_name="Delete Memory",
    description=(
        "Delete a previously saved memory by key. "
        "Use when the user asks you to forget something or when a stored fact is no longer accurate."
    ),
    params_schema={
        "key": {
            "type": "string",
            "description": "The key of the memory to delete.",
            "required": True,
        },
    },
    fn=memory_delete,
    requires_confirmation=False,
    requires_user_id=True,
))

