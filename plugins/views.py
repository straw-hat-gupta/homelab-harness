import logging
import urllib.parse

import requests
from django.conf import settings
from django.http import HttpResponseRedirect
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Credentials, OAuthState
from .serializers import (
    CredentialReadSerializer,
    CredentialWriteSerializer,
    ConnectSerializer,
    OAuthFinalizeSerializer,
)
from .plugins.registry import PLUGIN_REGISTRY
from .services.credentials import CredentialService

logger = logging.getLogger(__name__)


class OAuthAppRedirect(HttpResponseRedirect):
    """Redirect response that allows app-owned deep-link schemes."""
    allowed_schemes = [*HttpResponseRedirect.allowed_schemes, "aiva"]


def _oauth_redirect_target(setting_name: str, default: str, plugin_key: str) -> str:
    """Resolve a configured OAuth app redirect target.

    Args:
        setting_name: Django setting name to read.
        default: Fallback redirect target.
        plugin_key: Plugin key to substitute into plugin-aware redirect targets.

    Returns:
        Configured redirect target or fallback value.
    """
    target = getattr(settings, setting_name, default) or default
    try:
        return target.format(plugin=plugin_key)
    except (KeyError, IndexError, ValueError):
        logger.warning("Invalid OAuth redirect format for %s: %s", setting_name, target)
        return target


def _with_query_params(url: str, params: dict[str, str]) -> str:
    """Append query params to a URL or deep link."""
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query.extend(params.items())
    return urllib.parse.urlunparse(
        parsed._replace(query=urllib.parse.urlencode(query))
    )


def _oauth_redirect(
    setting_name: str,
    default: str,
    plugin_key: str,
    query_params: dict[str, str] | None = None,
) -> OAuthAppRedirect:
    """Build an app redirect response for an OAuth result.

    Args:
        setting_name: Django setting name containing the redirect target.
        default: Fallback redirect target.
        plugin_key: Plugin key to substitute into plugin-aware redirect targets.

    Returns:
        Redirect response that supports the app scheme.
    """
    target = _oauth_redirect_target(setting_name, default, plugin_key)
    if query_params:
        target = _with_query_params(target, query_params)
    return OAuthAppRedirect(target)


def _build_redirect_uri(request, redirect_path: str) -> str:
    """Build the provider-facing OAuth callback URI.

    Args:
        request: Incoming HTTP request.
        redirect_path: Callback path registered for the plugin.

    Returns:
        Absolute callback URI for the OAuth provider.
    """
    public_base = getattr(settings, "PUBLIC_BACKEND_URL", "").rstrip("/")
    if public_base:
        return f"{public_base}{redirect_path}"
    return request.build_absolute_uri(redirect_path)


class PluginRegistryView(APIView):
    """Return information about available plugins (from registry)."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        """Return connectable plugin metadata.

        Args:
            request: Authenticated DRF request.

        Returns:
            Response containing plugin keys, display names, and scopes.
        """
        out = []
        for key, cfg in PLUGIN_REGISTRY.items():
            out.append({
                "key": key,
                "display": cfg.get("display", key),
                "scopes": cfg.get("scopes", []),
            })
        return Response(out)


class StartConnectView(APIView):
    """Start OAuth flow for a plugin."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        """Create an OAuth authorization URL for a plugin.

        Args:
            request: Authenticated DRF request with a plugin key.

        Returns:
            Response containing the provider authorization URL.
        """
        serializer = ConnectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        plugin_key = serializer.validated_data["plugin"]

        if plugin_key not in PLUGIN_REGISTRY:
            return Response({"detail": "Unknown plugin"}, status=status.HTTP_400_BAD_REQUEST)

        cfg = PLUGIN_REGISTRY[plugin_key]

        # Ensure env variables exist; tests can override these
        client_id = getattr(settings, cfg.get("client_id_env", ""), "")
        if not client_id:
            return Response({"detail": f"{cfg.get('client_id_env')} not configured"}, status=500)

        redirect_uri = _build_redirect_uri(request, cfg["redirect_path"])

        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(cfg.get("scopes", [])),
            "state": CredentialService.generate_state(request.user, plugin_key),
        }
        params.update(cfg.get("extra_params", {}))

        url = f"{cfg['auth_url']}?{urllib.parse.urlencode(params)}"
        return Response({"auth_url": url})


class OAuthCallbackView(APIView):
    """Provider callback endpoint."""
    permission_classes = [permissions.AllowAny]

    def get(self, request, plugin_key):
        """Handle an OAuth provider callback.

        Args:
            request: Callback request containing code and state.
            plugin_key: Plugin registry key from the callback route.

        Returns:
            Redirect response to the configured app success or failure target.
        """
        code = request.GET.get("code")
        state = request.GET.get("state")
        error = request.GET.get("error")

        if error or not code or not state:
            logger.warning("OAuth callback missing code/state or provider error: %s", error)
            return _oauth_redirect(
                "PLUGIN_OAUTH_FAILURE_REDIRECT",
                "aiva://oauth/{plugin}/failure",
                plugin_key,
            )

        if plugin_key not in PLUGIN_REGISTRY:
            logger.error("Unknown plugin in callback: %s", plugin_key)
            return _oauth_redirect(
                "PLUGIN_OAUTH_FAILURE_REDIRECT",
                "aiva://oauth/{plugin}/failure",
                plugin_key,
            )

        try:
            oauth_state = CredentialService.validate_state_and_get_oauth_state(state, plugin_key)
        except Exception as e:
            logger.warning("Invalid OAuth state: %s", e)
            return _oauth_redirect(
                "PLUGIN_OAUTH_FAILURE_REDIRECT",
                "aiva://oauth/{plugin}/failure",
                plugin_key,
            )

        cfg = PLUGIN_REGISTRY[plugin_key]
        redirect_uri = _build_redirect_uri(request, cfg["redirect_path"])

        try:
            token_data = CredentialService.exchange_code(plugin_key, code, redirect_uri)
        except requests.HTTPError as e:
            logger.exception("Token exchange failed: %s", e)
            return _oauth_redirect(
                "PLUGIN_OAUTH_FAILURE_REDIRECT",
                "aiva://oauth/{plugin}/failure",
                plugin_key,
            )

        access_token = token_data.get("access_token") or token_data.get("token")
        expires_in = token_data.get("expires_in")
        if expires_in is None and not cfg.get("token_never_expires"):
            expires_in = 3600

        account_id = None
        if access_token:
            try:
                account_id = CredentialService.fetch_account_id(plugin_key, access_token)
            except Exception:
                logger.exception("Failed to fetch account ID for %s", plugin_key)

        if expires_in is not None:
            token_data["expires_in"] = expires_in
        try:
            completion_token = CredentialService.store_pending_oauth_result(
                oauth_state,
                token_data,
                account_id,
                cfg.get("scopes", []),
            )
        except ValueError as exc:
            logger.warning("Invalid OAuth token response for %s: %s", plugin_key, exc)
            return _oauth_redirect(
                "PLUGIN_OAUTH_FAILURE_REDIRECT",
                "aiva://oauth/{plugin}/failure",
                plugin_key,
            )

        return _oauth_redirect(
            "PLUGIN_OAUTH_SUCCESS_REDIRECT",
            "aiva://oauth/{plugin}/success",
            plugin_key,
            {"completion_token": completion_token},
        )


class OAuthFinalizeView(APIView):
    """Finalize a pending OAuth callback from the authenticated app."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        """Commit a pending OAuth result to the authenticated user's credentials."""
        serializer = OAuthFinalizeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        plugin_key = serializer.validated_data["plugin"]
        completion_token = serializer.validated_data["completion_token"]

        if plugin_key not in PLUGIN_REGISTRY:
            return Response({"detail": "Unknown plugin"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            credential = CredentialService.finalize_oauth_connection(
                request.user,
                plugin_key,
                completion_token,
            )
        except PermissionError:
            logger.warning(
                "OAuth finalize user mismatch user_id=%s plugin=%s",
                request.user.pk,
                plugin_key,
            )
            return Response(
                {"detail": "OAuth completion token does not belong to this user"},
                status=status.HTTP_403_FORBIDDEN,
            )
        except OAuthState.DoesNotExist:
            return Response(
                {"detail": "Invalid OAuth completion token"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "detail": "Connected",
                "credential": CredentialReadSerializer(credential).data,
            },
            status=status.HTTP_200_OK,
        )


# Updated REST views to support POST, PUT, DELETE
class CredentialListCreateView(generics.ListAPIView):
    """List credentials for the logged-in user. Use the OAuth flow to add new credentials."""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = CredentialReadSerializer

    def get_queryset(self):
        """Return credentials owned by the authenticated user.

        Returns:
            Queryset scoped to the current request user.
        """
        return Credentials.objects.filter(user=self.request.user)


class CredentialDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update, or delete a credential."""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = CredentialReadSerializer
    lookup_field = "pk"

    def get_queryset(self):
        """Return credentials owned by the authenticated user.

        Returns:
            Queryset scoped to the current request user.
        """
        return Credentials.objects.filter(user=self.request.user)

    def get_serializer_class(self):
        """Select serializer based on request method.

        Returns:
            Write serializer for updates, otherwise read serializer.
        """
        if self.request.method in ("PUT", "PATCH"):
            return CredentialWriteSerializer
        return CredentialReadSerializer

    def update(self, request, *args, **kwargs):
        """Update a credential and return its redacted representation.

        Args:
            request: Authenticated DRF request with credential updates.
            *args: Additional DRF positional arguments.
            **kwargs: Additional DRF keyword arguments.

        Returns:
            Response containing redacted credential data.
        """
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(CredentialReadSerializer(instance).data, status=status.HTTP_200_OK)


class CredentialRefreshView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        """Refresh one stored credential.

        Args:
            request: Authenticated DRF request.
            pk: Credential primary key.

        Returns:
            Response indicating refresh success or failure.
        """
        try:
            creds = Credentials.objects.get(pk=pk, user=request.user)
        except Credentials.DoesNotExist:
            return Response({"detail": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        try:
            CredentialService.refresh_token(creds)
            return Response({"detail": "Refreshed"})
        except Exception as e:
            logger.exception("Refresh failed for credential %s: %s", pk, e)
            return Response({"detail": "Refresh failed. Please reconnect the plugin."}, status=status.HTTP_400_BAD_REQUEST)


class CredentialDisconnectView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        """Disconnect and delete one stored credential.

        Args:
            request: Authenticated DRF request.
            pk: Credential primary key.

        Returns:
            Empty 204 response when deleted.
        """
        try:
            creds = Credentials.objects.get(pk=pk, user=request.user)
        except Credentials.DoesNotExist:
            return Response({"detail": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        revoke_warning = None
        try:
            CredentialService.revoke(creds)
        except Exception:
            logger.exception("Failed revoke call; continuing to delete locally")
            revoke_warning = (
                "Credential removed locally, but the provider token could not be revoked. "
                "You may need to disconnect manually in your account settings."
            )

        creds.delete()
        if revoke_warning:
            return Response({"warning": revoke_warning}, status=status.HTTP_200_OK)
        return Response(status=status.HTTP_204_NO_CONTENT)
