# plugins/services/credentials.py
from __future__ import annotations

import time
import secrets
from datetime import timedelta, timezone as dt_timezone

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from plugins.models import Credentials, OAuthState
from plugins.plugins.registry import PLUGIN_REGISTRY

User = get_user_model()
_STATE_SALT = "plugins.oauth.state"
_STATE_MAX_AGE_SECONDS = 600


class CredentialService:
    @staticmethod
    def _setting(name: str) -> str:
        """Read a required Django setting.

        Args:
            name: Setting name to read.

        Returns:
            Configured setting value.
        """
        value = getattr(settings, name, "")
        if not value:
            raise RuntimeError(f"{name} is not configured")
        return value

    @staticmethod
    def exchange_code(plugin_key: str, code: str, redirect_uri: str) -> dict:
        """Exchange an OAuth authorization code for token data.

        Args:
            plugin_key: Plugin registry key.
            code: Authorization code from the provider callback.
            redirect_uri: Backend callback URI used for the OAuth flow.

        Returns:
            Provider token response as a dictionary.
        """
        cfg = PLUGIN_REGISTRY[plugin_key]
        token_url = cfg["token_url"]
        client_id = CredentialService._setting(cfg["client_id_env"])
        client_secret = CredentialService._setting(cfg["client_secret_env"])

        if cfg.get("token_auth_style") == "basic_json":
            resp = requests.post(
                token_url,
                json={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
                auth=(client_id, client_secret),
                headers={"Content-Type": "application/json"},
                timeout=15,
            )
        else:
            data = {
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            }
            resp = requests.post(token_url, data=data, timeout=15)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def refresh_token(creds: Credentials, max_retries: int = 2) -> Credentials:
        """Refresh an expired OAuth credential with retry on transient errors.

        Args:
            creds: Stored credential with a refresh token.
            max_retries: Maximum additional attempts after the first failure.

        Returns:
            Updated credential row.
        """
        if not creds.refresh_token:
            raise ValueError(f"Credential {creds.pk} does not have a refresh token")

        cfg = PLUGIN_REGISTRY[creds.plugin]
        token_url = cfg["token_url"]
        client_id = CredentialService._setting(cfg["client_id_env"])
        client_secret = CredentialService._setting(cfg["client_secret_env"])

        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": creds.refresh_token,
        }

        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                resp = requests.post(token_url, data=data, timeout=15)
                resp.raise_for_status()
                token_data = resp.json()
                CredentialService.save_token_data(creds, token_data)
                creds.status = "active"
                creds.last_error = None
                creds.save(update_fields=["status", "last_error", "updated_at"])
                return creds
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
                last_exc = exc
            except requests.exceptions.HTTPError as exc:
                if exc.response is not None and (exc.response.status_code >= 500 or exc.response.status_code == 429):
                    last_exc = exc
                else:
                    raise
            if attempt < max_retries:
                time.sleep(2 ** attempt)  # 1 s, 2 s

        raise last_exc  # type: ignore[misc]

    @staticmethod
    def get_active_credential(user, plugin: str, account_id: str | None = None) -> Credentials:
        """Load the newest active credential for a plugin.

        Args:
            user: Django user that owns the credential.
            plugin: Plugin registry key.
            account_id: Optional provider account identifier.

        Returns:
            Matching active credential row.
        """
        qs = Credentials.objects.filter(user=user, plugin=plugin, status="active")
        if account_id is not None:
            qs = qs.filter(account_id=account_id)
        creds = qs.order_by("-updated_at").first()
        if creds is None:
            detail = f"plugin {plugin!r}"
            if account_id is not None:
                detail += f" account {account_id!r}"
            raise Credentials.DoesNotExist(f"No active credential found for {detail}")
        return creds

    @staticmethod
    def ensure_valid_credential(creds: Credentials) -> Credentials:
        """Refresh a credential if needed and record usage.

        Args:
            creds: Stored credential row.

        Returns:
            Valid active credential row.
        """
        if creds.is_expired():
            try:
                creds = CredentialService.refresh_token(creds)
            except Exception as exc:
                creds.status = "error"
                creds.last_error = str(exc)
                creds.save(update_fields=["status", "last_error", "updated_at"])
                raise
        creds.mark_used()
        return creds

    @staticmethod
    def credential_to_token_data(creds: Credentials) -> dict:
        """Convert a credential row into provider token data.

        Args:
            creds: Stored credential row.

        Returns:
            Token dictionary for provider SDK clients.
        """
        token_data = {
            "access_token": creds.access_token,
            "refresh_token": creds.refresh_token,
        }
        if creds.expires_at:
            token_data["expiry"] = creds.expires_at.astimezone(
                dt_timezone.utc
            ).isoformat()
        return token_data

    @staticmethod
    def _token_expires_at(token_data: dict):
        expires_at = None
        if token_data.get("expires_in") is not None:
            expires_at = timezone.now() + timedelta(seconds=int(token_data["expires_in"]))
        elif token_data.get("expiry"):
            expires_at = parse_datetime(token_data["expiry"])

        if expires_at is not None and timezone.is_naive(expires_at):
            expires_at = timezone.make_aware(expires_at, dt_timezone.utc)
        return expires_at

    @staticmethod
    def save_token_data(creds: Credentials, token_data: dict) -> Credentials:
        """Persist provider token data onto a credential row.

        Args:
            creds: Credential row to update.
            token_data: Provider token payload.

        Returns:
            Updated credential row.
        """
        access_token = token_data.get("access_token") or token_data.get("token")
        if access_token:
            creds.access_token = access_token

        if token_data.get("refresh_token"):
            creds.refresh_token = token_data["refresh_token"]

        expires_at = CredentialService._token_expires_at(token_data)
        if expires_at is not None:
            creds.expires_at = expires_at

        creds.status = "active"
        creds.last_error = None
        creds.save(
            update_fields=[
                "access_token",
                "refresh_token",
                "expires_at",
                "status",
                "last_error",
                "updated_at",
            ]
        )
        return creds

    @staticmethod
    def generate_state(user, plugin_key: str) -> str:
        """Create a signed OAuth state value backed by a one-time DB record.

        Args:
            user: Django user starting the OAuth flow.
            plugin_key: Plugin registry key.

        Returns:
            Signed state string containing an opaque nonce.
        """
        now = timezone.now()
        OAuthState.objects.filter(expires_at__lt=now).delete()
        nonce = secrets.token_urlsafe(32)
        OAuthState.objects.create(
            user=user,
            plugin=plugin_key,
            nonce=nonce,
            expires_at=now + timedelta(seconds=_STATE_MAX_AGE_SECONDS),
        )
        payload = {"nonce": nonce}
        return signing.dumps(payload, salt=_STATE_SALT)

    @staticmethod
    def validate_state_and_get_user(state: str, expected_plugin: str):
        """Validate OAuth state and return the owning user.

        Args:
            state: Signed state string from the callback.
            expected_plugin: Plugin key expected for this callback route.

        Returns:
            Django user referenced by the consumed server-side state row.
        """
        return CredentialService.validate_state_and_get_oauth_state(
            state, expected_plugin
        ).user

    @staticmethod
    def validate_state_and_get_oauth_state(state: str, expected_plugin: str) -> OAuthState:
        """Validate OAuth state, consume it, and return the server-side state row.

        Args:
            state: Signed state string from the callback.
            expected_plugin: Plugin key expected for this callback route.

        Returns:
            Consumed OAuthState row with the initiating user preloaded.
        """
        payload = signing.loads(
            state,
            salt=_STATE_SALT,
            max_age=_STATE_MAX_AGE_SECONDS,
        )
        nonce = payload.get("nonce")
        if not nonce:
            raise ValueError("OAuth state missing nonce")

        with transaction.atomic():
            oauth_state = (
                OAuthState.objects.select_for_update()
                .select_related("user")
                .get(nonce=nonce)
            )
            now = timezone.now()
            if oauth_state.consumed_at is not None:
                raise ValueError("OAuth state already consumed")
            if oauth_state.expires_at <= now:
                raise ValueError("OAuth state expired")
            if oauth_state.plugin != expected_plugin:
                raise ValueError("OAuth state plugin mismatch")

            oauth_state.consumed_at = now
            oauth_state.save(update_fields=["consumed_at"])
            return oauth_state

    @staticmethod
    def store_pending_oauth_result(
        oauth_state: OAuthState,
        token_data: dict,
        account_id: str | None,
        scopes: list[str],
    ) -> str:
        """Store exchanged provider tokens until the app finalizes OAuth.

        Args:
            oauth_state: Consumed OAuth state row.
            token_data: Provider token payload from code exchange.
            account_id: Provider account label, if available.
            scopes: Granted/configured plugin scopes.

        Returns:
            Opaque completion token to send back to the app.
        """
        access_token = token_data.get("access_token") or token_data.get("token")
        if not access_token:
            raise ValueError("OAuth token response did not include an access token")

        finalize_nonce = secrets.token_urlsafe(32)
        oauth_state.finalize_nonce = finalize_nonce
        oauth_state.account_id = account_id
        oauth_state.access_token = access_token
        oauth_state.refresh_token = token_data.get("refresh_token") or None
        oauth_state.scopes = scopes
        oauth_state.token_expires_at = CredentialService._token_expires_at(token_data)
        oauth_state.save(
            update_fields=[
                "finalize_nonce",
                "account_id",
                "access_token",
                "refresh_token",
                "scopes",
                "token_expires_at",
            ]
        )
        return finalize_nonce

    @staticmethod
    def finalize_oauth_connection(user, plugin_key: str, completion_token: str) -> Credentials:
        """Commit a pending OAuth result to PluginCredentials for the authenticated user.

        Args:
            user: Authenticated app user finalizing OAuth.
            plugin_key: Plugin registry key.
            completion_token: Opaque token returned to the app deep link.

        Returns:
            Created or updated credential row.
        """
        with transaction.atomic():
            oauth_state = (
                OAuthState.objects.select_for_update()
                .select_related("user")
                .get(finalize_nonce=completion_token, plugin=plugin_key)
            )
            now = timezone.now()
            if oauth_state.finalized_at is not None:
                raise ValueError("OAuth result already finalized")
            if oauth_state.expires_at <= now:
                raise ValueError("OAuth result expired")
            if oauth_state.user_id != user.pk:
                raise PermissionError("OAuth result belongs to a different user")
            if not oauth_state.access_token:
                raise ValueError("OAuth result is missing token data")

            credential_defaults = {
                "access_token": oauth_state.access_token,
                "expires_at": oauth_state.token_expires_at,
                "scopes": oauth_state.scopes or PLUGIN_REGISTRY[plugin_key].get("scopes", []),
                "status": "active",
            }
            if oauth_state.refresh_token:
                credential_defaults["refresh_token"] = oauth_state.refresh_token

            credential, _ = Credentials.objects.update_or_create(
                user=user,
                plugin=plugin_key,
                account_id=oauth_state.account_id,
                defaults=credential_defaults,
            )

            oauth_state.finalized_at = now
            oauth_state.finalize_nonce = None
            oauth_state.access_token = None
            oauth_state.refresh_token = None
            oauth_state.save(
                update_fields=[
                    "finalized_at",
                    "finalize_nonce",
                    "access_token",
                    "refresh_token",
                ]
            )
            return credential

    @staticmethod
    def fetch_account_id(plugin_key: str, access_token: str) -> str | None:
        """Fetch a stable provider account identifier using the registry config.

        Args:
            plugin_key: Plugin registry key.
            access_token: Provider access token.

        Returns:
            Provider account identifier, or None when not configured.
        """
        cfg = PLUGIN_REGISTRY.get(plugin_key, {})
        endpoint = cfg.get("account_id_endpoint")
        if not endpoint:
            return None
        headers = {"Authorization": f"Bearer {access_token}"}
        headers.update(endpoint.get("headers", {}))
        resp = requests.get(
            endpoint["url"],
            headers=headers,
            params=endpoint.get("params", {}),
            timeout=15,
        )
        resp.raise_for_status()
        data: object = resp.json()
        for key in endpoint["field"].split("."):
            if not isinstance(data, dict):
                return None
            data = data.get(key)
        return data if isinstance(data, str) else None

    @staticmethod
    def revoke(creds: Credentials) -> None:
        """Revoke a provider token when the plugin supports revocation.

        Args:
            creds: Credential row being disconnected.

        Returns:
            None.
        """
        cfg = PLUGIN_REGISTRY.get(creds.plugin, {})
        revoke_url = cfg.get("revoke_url")
        if not revoke_url:
            return

        token = creds.refresh_token or creds.access_token
        if not token:
            return

        resp = requests.post(
            revoke_url,
            params={"token": token},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        resp.raise_for_status()
