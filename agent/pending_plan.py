"""
DB-backed store for plans awaiting user confirmation.
Stored in Projects.pending_plan (JSONField) for project chats.
Falls back to Django cache (TTL 2 h) when project_id is not a valid Projects PK
(e.g. the literal string "default" used for non-project chats).
"""
from typing import Optional

from planner.schemas import Plan

_PENDING_PLAN_CACHE_TTL = 7200  # 2 hours


def _pending_cache_key(user_id: str, project_id: str) -> str:
    return f"pending_plan:{user_id}:{project_id}"


def _get_project(user_id: str, project_id: str):
    """Load a project owned by a Supabase user.

    Args:
        user_id: Supabase UID of the project owner.
        project_id: Project primary key as a string.

    Returns:
        Matching project, or None.
    """
    try:
        pid = int(project_id)
    except (ValueError, TypeError):
        return None
    from django.contrib.auth import get_user_model
    from projects.models import Projects
    User = get_user_model()
    try:
        user = User.objects.get(supabase_uid=user_id)
        return Projects.objects.get(pk=pid, user=user)
    except Exception:
        return None


def save(user_id: str, project_id: str, plan: Plan) -> None:
    """Store a pending plan on a project.

    Args:
        user_id: Supabase UID of the project owner.
        project_id: Project primary key as a string.
        plan: Plan awaiting user confirmation.

    Returns:
        None.
    """
    project = _get_project(user_id, project_id)
    if project is None:
        from django.core.cache import cache
        cache.set(_pending_cache_key(user_id, project_id), plan.model_dump_json(), _PENDING_PLAN_CACHE_TTL)
        return
    project.pending_plan = plan.model_dump()
    project.save(update_fields=["pending_plan", "updated_at"])


def load(user_id: str, project_id: str) -> Optional[Plan]:
    """Load a pending plan from a project.

    Args:
        user_id: Supabase UID of the project owner.
        project_id: Project primary key as a string.

    Returns:
        Pending plan, or None.
    """
    project = _get_project(user_id, project_id)
    if project is None:
        from django.core.cache import cache
        cached = cache.get(_pending_cache_key(user_id, project_id))
        if cached is None:
            return None
        return Plan.model_validate_json(cached)
    if project.pending_plan is None:
        return None
    return Plan.model_validate(project.pending_plan)


# ---------------------------------------------------------------------------
# Modify-count helpers (cache-backed; lives as long as the pending plan)
# ---------------------------------------------------------------------------

_MODIFY_COUNT_TTL = 7200  # 2 hours; longer than any realistic session


def _modify_key(user_id: str, project_id: str) -> str:
    """Build the cache key for pending-plan modify counts.

    Args:
        user_id: Supabase UID of the project owner.
        project_id: Project primary key as a string.

    Returns:
        Cache key string.
    """
    return f"pending_modify_count:{user_id}:{project_id}"


def get_modify_count(user_id: str, project_id: str) -> int:
    """Read the number of modifications for a pending plan.

    Args:
        user_id: Supabase UID of the project owner.
        project_id: Project primary key as a string.

    Returns:
        Current modify count.
    """
    from django.core.cache import cache
    return cache.get(_modify_key(user_id, project_id), 0)


def increment_modify_count(user_id: str, project_id: str) -> int:
    """Increment the pending-plan modify count.

    Args:
        user_id: Supabase UID of the project owner.
        project_id: Project primary key as a string.

    Returns:
        Updated modify count.
    """
    from django.core.cache import cache
    key = _modify_key(user_id, project_id)
    count = (cache.get(key) or 0) + 1
    cache.set(key, count, _MODIFY_COUNT_TTL)
    return count


def reset_modify_count(user_id: str, project_id: str) -> None:
    """Reset the pending-plan modify count.

    Args:
        user_id: Supabase UID of the project owner.
        project_id: Project primary key as a string.

    Returns:
        None.
    """
    from django.core.cache import cache
    cache.delete(_modify_key(user_id, project_id))


def clear(user_id: str, project_id: str) -> None:
    """Clear a project's pending plan.

    Args:
        user_id: Supabase UID of the project owner.
        project_id: Project primary key as a string.

    Returns:
        None.
    """
    project = _get_project(user_id, project_id)
    if project is None:
        from django.core.cache import cache
        cache.delete(_pending_cache_key(user_id, project_id))
        return
    project.pending_plan = None
    project.save(update_fields=["pending_plan", "updated_at"])
