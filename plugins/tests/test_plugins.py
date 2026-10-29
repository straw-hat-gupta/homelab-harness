import uuid
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import requests
from cryptography.fernet import Fernet, InvalidToken
from django.contrib.auth import get_user_model
from django.core import signing
from django.db import connection
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from plugins.models import Credentials, OAuthState
from plugins.views import OAuthAppRedirect

User = get_user_model()

_TEST_ENCRYPTION_KEY = Fernet.generate_key().decode()


@override_settings(
    GOOGLE_CLIENT_ID="fake-client-id",
    GOOGLE_CLIENT_SECRET="fake-client-secret",
    PLUGIN_OAUTH_FAILURE_REDIRECT="aiva://oauth/{plugin}/failure",
    PLUGIN_OAUTH_SUCCESS_REDIRECT="aiva://oauth/{plugin}/success",
    PUBLIC_BACKEND_URL="http://testserver",
    CREDENTIAL_ENCRYPTION_KEY=_TEST_ENCRYPTION_KEY,
)
class CredentialsTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create(
            email="test@example.com",
            supabase_uid=uuid.uuid4(),
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _create_credentials(self, plugin, access_token, refresh_token=None):
        return Credentials.objects.create(
            user=self.user, plugin=plugin, access_token=access_token, refresh_token=refresh_token
        )

    # ---------- Auth ----------

    def test_unauthenticated_returns_4xx(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(reverse("credentials-list"))
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    # ---------- CRUD ----------

    def test_list_credentials(self):
        response = self.client.get(reverse("credentials-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

        self._create_credentials("gmail", "token123")
        self._create_credentials("slack", "token456")

        response = self.client.get(reverse("credentials-list"))
        self.assertEqual(len(response.data), 2)

    def test_retrieve_credentials(self):
        creds = self._create_credentials("gmail", "token123")
        url = reverse("credentials-detail", kwargs={"pk": creds.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["plugin"], "gmail")

    def test_create_credentials_not_allowed(self):
        """Direct credential POST is disabled; credentials are created via OAuth flow."""
        data = {"plugin": "gmail", "access_token": "tok123", "refresh_token": "ref123"}
        response = self.client.post(reverse("credentials-list"), data)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_update_credentials(self):
        creds = self._create_credentials("gmail", "oldtoken")
        url = reverse("credentials-detail", kwargs={"pk": creds.id})
        response = self.client.put(url, {"plugin": "gmail", "access_token": "newtoken"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("access_token", response.data)
        creds.refresh_from_db()
        self.assertEqual(creds.access_token, "newtoken")

    def test_delete_credentials(self):
        creds = self._create_credentials("gmail", "token123")
        url = reverse("credentials-detail", kwargs={"pk": creds.id})
        self.assertEqual(self.client.delete(url).status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(self.client.get(url).status_code, status.HTTP_404_NOT_FOUND)

    # ---------- OAuth flow ----------

    def test_initiate_oauth(self):
        response = self.client.post(reverse("credentials-initiate-oauth"), {"plugin": "gmail"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("auth_url", response.data)
        qs = parse_qs(urlparse(response.data["auth_url"]).query)
        self.assertIn("state", qs)
        self.assertEqual(qs["redirect_uri"][0], "http://testserver/plugins/oauth/callback/gmail/")
        oauth_state = OAuthState.objects.get(user=self.user, plugin="gmail")
        payload = signing.loads(qs["state"][0], salt="plugins.oauth.state")
        self.assertEqual(payload, {"nonce": oauth_state.nonce})
        self.assertIsNone(oauth_state.consumed_at)

    def test_registry_includes_google_drive(self):
        response = self.client.get(reverse("plugin-registry"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        by_key = {item["key"]: item for item in response.data}
        self.assertIn("google_drive", by_key)
        self.assertEqual(by_key["google_drive"]["display"], "Google Drive")
        self.assertEqual(
            by_key["google_drive"]["scopes"],
            ["https://www.googleapis.com/auth/drive.readonly"],
        )

    def test_initiate_google_drive_oauth(self):
        response = self.client.post(reverse("credentials-initiate-oauth"), {"plugin": "google_drive"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("auth_url", response.data)
        qs = parse_qs(urlparse(response.data["auth_url"]).query)
        self.assertIn("state", qs)
        self.assertEqual(
            qs["redirect_uri"][0],
            "http://testserver/plugins/oauth/callback/google_drive/",
        )
        self.assertEqual(
            qs["scope"][0],
            "https://www.googleapis.com/auth/drive.readonly",
        )

    def test_oauth_redirect_helper_allows_aiva_scheme(self):
        response = OAuthAppRedirect("aiva://oauth/gmail/success")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "aiva://oauth/gmail/success")

    def test_callback_missing_code_redirects_to_failure(self):
        url = reverse("credentials-callback-oauth", kwargs={"plugin_key": "gmail"})
        response = self.client.get(url, {"plugin": "gmail"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "aiva://oauth/gmail/failure")

    def test_callback_invalid_state_redirects_to_failure(self):
        url = reverse("credentials-callback-oauth", kwargs={"plugin_key": "gmail"})
        response = self.client.get(url, {"code": "oauth-code", "state": "invalid"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "aiva://oauth/gmail/failure")

    def test_callback_legacy_signed_state_without_nonce_redirects_to_failure(self):
        state = signing.dumps(
            {"user_id": self.user.pk, "plugin": "gmail"},
            salt="plugins.oauth.state",
        )
        url = reverse("credentials-callback-oauth", kwargs={"plugin_key": "gmail"})
        response = self.client.get(url, {"code": "oauth-code", "state": state})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "aiva://oauth/gmail/failure")

    @patch("plugins.views.CredentialService.fetch_account_id", return_value="user@gmail.com")
    @patch(
        "plugins.views.CredentialService.exchange_code",
        return_value={"access_token": "tok123", "refresh_token": "ref123", "expires_in": 3600},
    )
    def test_callback_success_consumes_oauth_state_once(self, mock_exchange, mock_fetch):
        connect = self.client.post(reverse("credentials-initiate-oauth"), {"plugin": "gmail"})
        state = parse_qs(urlparse(connect.data["auth_url"]).query)["state"][0]
        url = reverse("credentials-callback-oauth", kwargs={"plugin_key": "gmail"})

        response = self.client.get(url, {"code": "oauth-code", "state": state})

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("aiva://oauth/gmail/success?"))
        completion_token = parse_qs(urlparse(response["Location"]).query)["completion_token"][0]
        self.assertTrue(completion_token)
        oauth_state = OAuthState.objects.get(user=self.user, plugin="gmail")
        self.assertIsNotNone(oauth_state.consumed_at)
        self.assertIsNotNone(oauth_state.finalize_nonce)
        self.assertEqual(oauth_state.account_id, "user@gmail.com")
        self.assertEqual(oauth_state.access_token, "tok123")
        self.assertFalse(Credentials.objects.filter(user=self.user, plugin="gmail").exists())

        replay = self.client.get(url, {"code": "oauth-code-2", "state": state})
        self.assertEqual(replay.status_code, 302)
        self.assertEqual(replay["Location"], "aiva://oauth/gmail/failure")
        mock_exchange.assert_called_once_with(
            "gmail", "oauth-code", "http://testserver/plugins/oauth/callback/gmail/"
        )

    @patch("plugins.views.CredentialService.exchange_code")
    def test_callback_mismatched_server_state_plugin_redirects_to_failure(self, mock_exchange):
        connect = self.client.post(reverse("credentials-initiate-oauth"), {"plugin": "gmail"})
        state = parse_qs(urlparse(connect.data["auth_url"]).query)["state"][0]
        url = reverse("credentials-callback-oauth", kwargs={"plugin_key": "google_drive"})

        response = self.client.get(url, {"code": "oauth-code", "state": state})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "aiva://oauth/google_drive/failure")
        mock_exchange.assert_not_called()

    @patch("plugins.views.CredentialService.exchange_code")
    def test_callback_expired_server_state_redirects_to_failure(self, mock_exchange):
        connect = self.client.post(reverse("credentials-initiate-oauth"), {"plugin": "gmail"})
        state = parse_qs(urlparse(connect.data["auth_url"]).query)["state"][0]
        OAuthState.objects.filter(user=self.user, plugin="gmail").update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        url = reverse("credentials-callback-oauth", kwargs={"plugin_key": "gmail"})

        response = self.client.get(url, {"code": "oauth-code", "state": state})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "aiva://oauth/gmail/failure")
        mock_exchange.assert_not_called()

    def test_google_drive_callback_missing_code_redirects_to_failure(self):
        url = reverse("credentials-callback-oauth", kwargs={"plugin_key": "google_drive"})
        response = self.client.get(url, {"plugin": "google_drive"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "aiva://oauth/google_drive/failure")

    @patch("plugins.views.CredentialService.exchange_code", side_effect=requests.HTTPError("boom"))
    @patch("plugins.views.CredentialService.validate_state_and_get_oauth_state")
    def test_callback_token_exchange_failure_redirects_to_failure(
        self, mock_validate, mock_exchange
    ):
        mock_validate.return_value = OAuthState(user=self.user, plugin="gmail")
        url = reverse("credentials-callback-oauth", kwargs={"plugin_key": "gmail"})
        response = self.client.get(url, {"code": "oauth-code", "state": "signed-state"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "aiva://oauth/gmail/failure")
        mock_validate.assert_called_once_with("signed-state", "gmail")

    @patch("plugins.views.CredentialService.fetch_account_id", return_value="user@gmail.com")
    @patch(
        "plugins.views.CredentialService.exchange_code",
        return_value={"access_token": "tok123", "refresh_token": "ref123", "expires_in": 3600},
    )
    def test_callback_success_redirects_with_completion_token_without_saving_credentials(
        self, mock_exchange, mock_fetch
    ):
        connect = self.client.post(reverse("credentials-initiate-oauth"), {"plugin": "gmail"})
        state = parse_qs(urlparse(connect.data["auth_url"]).query)["state"][0]
        url = reverse("credentials-callback-oauth", kwargs={"plugin_key": "gmail"})

        response = self.client.get(url, {"code": "oauth-code", "state": state})

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("aiva://oauth/gmail/success?"))
        completion_token = parse_qs(urlparse(response["Location"]).query)["completion_token"][0]
        self.assertTrue(completion_token)
        mock_exchange.assert_called_once_with(
            "gmail", "oauth-code", "http://testserver/plugins/oauth/callback/gmail/"
        )
        oauth_state = OAuthState.objects.get(user=self.user, plugin="gmail")
        self.assertEqual(oauth_state.finalize_nonce, completion_token)
        self.assertEqual(oauth_state.account_id, "user@gmail.com")
        self.assertEqual(oauth_state.access_token, "tok123")
        self.assertEqual(oauth_state.refresh_token, "ref123")
        self.assertFalse(Credentials.objects.filter(user=self.user, plugin="gmail").exists())

    @patch("plugins.views.CredentialService.fetch_account_id", return_value="user@gmail.com")
    @patch(
        "plugins.views.CredentialService.exchange_code",
        return_value={"access_token": "tok123", "refresh_token": "ref123", "expires_in": 3600},
    )
    def test_oauth_finalize_saves_credentials_for_initiating_user(
        self, mock_exchange, mock_fetch
    ):
        connect = self.client.post(reverse("credentials-initiate-oauth"), {"plugin": "gmail"})
        state = parse_qs(urlparse(connect.data["auth_url"]).query)["state"][0]
        callback_url = reverse("credentials-callback-oauth", kwargs={"plugin_key": "gmail"})
        callback = self.client.get(callback_url, {"code": "oauth-code", "state": state})
        completion_token = parse_qs(urlparse(callback["Location"]).query)["completion_token"][0]

        response = self.client.post(
            reverse("credentials-finalize-oauth"),
            {"plugin": "gmail", "completion_token": completion_token},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["detail"], "Connected")
        creds = Credentials.objects.get(user=self.user, plugin="gmail", account_id="user@gmail.com")
        self.assertEqual(creds.access_token, "tok123")
        self.assertEqual(creds.refresh_token, "ref123")
        self.assertEqual(creds.status, "active")
        oauth_state = OAuthState.objects.get(user=self.user, plugin="gmail")
        self.assertIsNotNone(oauth_state.finalized_at)
        self.assertIsNone(oauth_state.access_token)
        self.assertIsNone(oauth_state.refresh_token)

        replay = self.client.post(
            reverse("credentials-finalize-oauth"),
            {"plugin": "gmail", "completion_token": completion_token},
        )
        self.assertEqual(replay.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("plugins.views.CredentialService.fetch_account_id", return_value="victim@gmail.com")
    @patch(
        "plugins.views.CredentialService.exchange_code",
        return_value={"access_token": "victim-token", "refresh_token": "victim-refresh", "expires_in": 3600},
    )
    def test_oauth_finalize_rejects_different_authenticated_user(
        self, mock_exchange, mock_fetch
    ):
        attacker = self.user
        victim = User.objects.create(email="victim@example.com", supabase_uid=uuid.uuid4())
        connect = self.client.post(reverse("credentials-initiate-oauth"), {"plugin": "gmail"})
        state = parse_qs(urlparse(connect.data["auth_url"]).query)["state"][0]
        callback_url = reverse("credentials-callback-oauth", kwargs={"plugin_key": "gmail"})
        callback = self.client.get(callback_url, {"code": "oauth-code", "state": state})
        completion_token = parse_qs(urlparse(callback["Location"]).query)["completion_token"][0]

        self.client.force_authenticate(user=victim)
        response = self.client.post(
            reverse("credentials-finalize-oauth"),
            {"plugin": "gmail", "completion_token": completion_token},
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Credentials.objects.filter(user=attacker, plugin="gmail").exists())
        self.assertFalse(Credentials.objects.filter(user=victim, plugin="gmail").exists())

    @patch("plugins.views.CredentialService.fetch_account_id", return_value="user@gmail.com")
    @patch(
        "plugins.views.CredentialService.exchange_code",
        return_value={"access_token": "new-access", "expires_in": 3600},
    )
    def test_callback_without_refresh_token_preserves_existing_refresh_token(
        self, mock_exchange, mock_fetch
    ):
        existing = Credentials.objects.create(
            user=self.user,
            plugin="gmail",
            account_id="user@gmail.com",
            access_token="old-access",
            refresh_token="old-refresh",
            status="active",
        )

        connect = self.client.post(reverse("credentials-initiate-oauth"), {"plugin": "gmail"})
        state = parse_qs(urlparse(connect.data["auth_url"]).query)["state"][0]
        callback_url = reverse("credentials-callback-oauth", kwargs={"plugin_key": "gmail"})
        callback = self.client.get(callback_url, {"code": "oauth-code", "state": state})
        completion_token = parse_qs(urlparse(callback["Location"]).query)["completion_token"][0]

        response = self.client.post(
            reverse("credentials-finalize-oauth"),
            {"plugin": "gmail", "completion_token": completion_token},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        existing.refresh_from_db()
        self.assertEqual(existing.access_token, "new-access")
        self.assertEqual(existing.refresh_token, "old-refresh")

    @patch("plugins.views.CredentialService.fetch_account_id", return_value="drive-user@gmail.com")
    @patch(
        "plugins.views.CredentialService.exchange_code",
        return_value={"access_token": "tok-drive", "refresh_token": "ref-drive", "expires_in": 3600},
    )
    def test_google_drive_callback_success_redirects_and_finalize_saves_credentials(
        self, mock_exchange, mock_fetch
    ):
        connect = self.client.post(reverse("credentials-initiate-oauth"), {"plugin": "google_drive"})
        state = parse_qs(urlparse(connect.data["auth_url"]).query)["state"][0]
        url = reverse("credentials-callback-oauth", kwargs={"plugin_key": "google_drive"})
        response = self.client.get(url, {"code": "oauth-code", "state": state})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("aiva://oauth/google_drive/success?"))
        completion_token = parse_qs(urlparse(response["Location"]).query)["completion_token"][0]
        mock_exchange.assert_called_once_with(
            "google_drive",
            "oauth-code",
            "http://testserver/plugins/oauth/callback/google_drive/",
        )
        response = self.client.post(
            reverse("credentials-finalize-oauth"),
            {"plugin": "google_drive", "completion_token": completion_token},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        creds = Credentials.objects.get(
            user=self.user,
            plugin="google_drive",
            account_id="drive-user@gmail.com",
        )
        self.assertEqual(creds.access_token, "tok-drive")
        self.assertEqual(creds.status, "active")

    @patch("plugins.views.CredentialService.refresh_token")
    def test_google_drive_refresh_endpoint_works(self, mock_refresh):
        creds = self._create_credentials("google_drive", "tok123", refresh_token="ref123")
        mock_refresh.return_value = creds
        url = reverse("credentials-refresh", kwargs={"pk": creds.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["detail"], "Refreshed")
        mock_refresh.assert_called_once_with(creds)

    def test_tokens_are_encrypted_at_rest(self):
        """Raw DB value must not be plaintext — Fernet ciphertext starts with 'gAAAAA'."""
        creds = self._create_credentials("gmail", "supersecret", refresh_token="refresh123")
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT access_token, refresh_token FROM "PluginCredentials" WHERE id = %s',
                [creds.id],
            )
            raw_access, raw_refresh = cursor.fetchone()
        self.assertNotEqual(raw_access, "supersecret", "access_token stored as plaintext")
        self.assertTrue(raw_access.startswith("gAAAAA"), f"unexpected raw value: {raw_access[:20]}")
        self.assertNotEqual(raw_refresh, "refresh123", "refresh_token stored as plaintext")
        self.assertTrue(raw_refresh.startswith("gAAAAA"), f"unexpected raw refresh: {raw_refresh[:20]}")

    @override_settings(CREDENTIAL_ENCRYPTION_ALLOW_PLAINTEXT_FALLBACK=False)
    def test_plaintext_token_read_fails_closed_by_default(self):
        creds = self._create_credentials("gmail", "initial-token")
        with connection.cursor() as cursor:
            cursor.execute(
                'UPDATE "PluginCredentials" SET access_token = %s WHERE id = %s',
                ["plaintext-token", creds.id],
            )

        with self.assertRaises(InvalidToken):
            Credentials.objects.get(pk=creds.id)

    @override_settings(CREDENTIAL_ENCRYPTION_ALLOW_PLAINTEXT_FALLBACK=True)
    def test_plaintext_token_read_requires_explicit_fallback(self):
        creds = self._create_credentials("gmail", "initial-token")
        with connection.cursor() as cursor:
            cursor.execute(
                'UPDATE "PluginCredentials" SET access_token = %s WHERE id = %s',
                ["plaintext-token", creds.id],
            )

        with self.assertLogs("plugins.fields", level="WARNING"):
            loaded = Credentials.objects.get(pk=creds.id)
        self.assertEqual(loaded.access_token, "plaintext-token")


@override_settings(CREDENTIAL_ENCRYPTION_KEY=_TEST_ENCRYPTION_KEY)
class GetActiveCredentialMultiAccountTests(APITestCase):
    """CredentialService.get_active_credential() with account_id parameter."""

    def setUp(self):
        self.user = User.objects.create(
            email="multi@example.com",
            supabase_uid=uuid.uuid4(),
        )

    def _cred(self, plugin, account_id=None, token="tok"):
        return Credentials.objects.create(
            user=self.user,
            plugin=plugin,
            account_id=account_id,
            access_token=token,
            status="active",
        )

    def test_selects_correct_account_when_multiple_connected(self):
        from plugins.services.credentials import CredentialService

        self._cred("gmail", "a@gmail.com", "tok-a")
        self._cred("gmail", "b@gmail.com", "tok-b")

        cred_a = CredentialService.get_active_credential(self.user, "gmail", account_id="a@gmail.com")
        self.assertEqual(cred_a.account_id, "a@gmail.com")
        cred_b = CredentialService.get_active_credential(self.user, "gmail", account_id="b@gmail.com")
        self.assertEqual(cred_b.account_id, "b@gmail.com")

    def test_no_account_id_returns_most_recently_updated(self):
        from plugins.services.credentials import CredentialService

        self._cred("gmail", "old@gmail.com", "tok-old")
        self._cred("gmail", "new@gmail.com", "tok-new")  # created later → updated_at is greater

        cred = CredentialService.get_active_credential(self.user, "gmail")
        self.assertEqual(cred.account_id, "new@gmail.com")

    def test_single_account_plugin_with_null_account_id_works(self):
        from plugins.services.credentials import CredentialService

        self._cred("google_calendar", None, "cal-tok")
        cred = CredentialService.get_active_credential(self.user, "google_calendar")
        self.assertEqual(cred.plugin, "google_calendar")

    def test_nonexistent_account_id_raises_does_not_exist(self):
        from plugins.services.credentials import CredentialService

        self._cred("gmail", "a@gmail.com", "tok-a")
        with self.assertRaises(Credentials.DoesNotExist):
            CredentialService.get_active_credential(self.user, "gmail", account_id="missing@gmail.com")
