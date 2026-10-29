from typing import List

from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from plugins.services.credentials import CredentialService

User = get_user_model()


@sync_to_async
def _load_token_data(user_id: str, plugin_id: str, account_id: str | None = None) -> dict:
    """Load valid token data for a user/plugin pair.

    Args:
        user_id: Supabase UID of the credential owner.
        plugin_id: Plugin registry key.
        account_id: Optional provider account identifier.

    Returns:
        Provider token data dictionary.
    """
    try:
        user = User.objects.get(supabase_uid=user_id)
    except User.DoesNotExist:
        raise PermissionError(f"No user found for supabase_uid={user_id!r}")
    creds = CredentialService.get_active_credential(user, plugin_id, account_id=account_id)
    creds = CredentialService.ensure_valid_credential(creds)
    return CredentialService.credential_to_token_data(creds)


@sync_to_async
def _save_token_data(user_id: str, plugin_id: str, token_data: dict) -> None:
    """Persist refreshed token data for a user/plugin pair.

    Args:
        user_id: Supabase UID of the credential owner.
        plugin_id: Plugin registry key.
        token_data: Provider token payload.

    Returns:
        None.
    """
    try:
        user = User.objects.get(supabase_uid=user_id)
    except User.DoesNotExist:
        return
    creds = CredentialService.get_active_credential(user, plugin_id)
    CredentialService.save_token_data(creds, token_data)


async def load_credentials(user_id: str, plugin_id: str, account_id: str | None = None) -> dict:
    """Load OAuth token data for a user and plugin.

    Args:
        user_id: Supabase UID of the credential owner.
        plugin_id: Plugin registry key.
        account_id: Optional provider account identifier.

    Returns:
        Provider token data dictionary.
    """
    return await _load_token_data(user_id, plugin_id, account_id)


async def save_credentials(user_id: str, plugin_id: str, creds: dict) -> None:
    """Persist refreshed OAuth token data.

    Args:
        user_id: Supabase UID of the credential owner.
        plugin_id: Plugin registry key.
        creds: Provider token payload.

    Returns:
        None.
    """
    await _save_token_data(user_id, plugin_id, creds)


@sync_to_async
def _list_connected(user_id: str) -> List[str]:
    """List plugin IDs with active credentials for a user.

    Args:
        user_id: Supabase UID of the credential owner.

    Returns:
        List of connected plugin IDs.
    """
    from plugins.models import Credentials as PluginCredentials
    try:
        user = User.objects.get(supabase_uid=user_id)
    except User.DoesNotExist:
        return []
    return list(
        PluginCredentials.objects.filter(user=user, status="active")
        .values_list("plugin", flat=True)
        .distinct()
    )


async def get_connected_plugins(user_id: str) -> List[str]:
    """Return plugin IDs with active credentials.

    Args:
        user_id: Supabase UID of the credential owner.

    Returns:
        List of connected plugin IDs.
    """
    return await _list_connected(user_id)


@sync_to_async
def _list_connected_accounts(user_id: str) -> List[dict]:
    """List active plugin/account credential pairs.

    Args:
        user_id: Supabase UID of the credential owner.

    Returns:
        List of dictionaries with plugin and account_id fields.
    """
    from plugins.models import Credentials as PluginCredentials
    try:
        user = User.objects.get(supabase_uid=user_id)
    except User.DoesNotExist:
        return []
    return list(
        PluginCredentials.objects.filter(user=user, status="active")
        .order_by("plugin", "account_id")
        .values("plugin", "account_id")
    )


async def get_connected_accounts(user_id: str) -> List[dict]:
    """Return active plugin/account credential pairs.

    Args:
        user_id: Supabase UID of the credential owner.

    Returns:
        List of dictionaries with plugin and account_id fields.
    """
    return await _list_connected_accounts(user_id)
