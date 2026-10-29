# Plugins App

The `plugins` app owns OAuth lifecycle and credential CRUD for third-party integrations.

## Live responsibilities

- expose the plugin registry
- start OAuth flows
- handle OAuth callbacks
- store pending callback token data in `PluginOAuthStates`
- finalize OAuth and store credentials in `PluginCredentials`
- refresh credentials through `CredentialService`
- provide redacted credential read APIs

The orchestrator uses the database-backed credentials in `PluginCredentials`. It no longer depends on `token.json`.

## Routes

| Method | Path | Description |
|---|---|---|
| `GET` | `/plugins/registry/` | Available plugins and scopes |
| `POST` | `/plugins/oauth/connect/` | Start OAuth flow |
| `GET` | `/plugins/oauth/callback/<plugin_key>/` | OAuth callback |
| `POST` | `/plugins/oauth/finalize/` | Authenticated app-side OAuth completion |
| `GET/POST` | `/plugins/credentials/` | List or create credentials |
| `GET/PUT/PATCH/DELETE` | `/plugins/credentials/<id>/` | Read/update/delete credential |
| `POST` | `/plugins/credentials/<id>/refresh/` | Force refresh credential |
| `POST` | `/plugins/credentials/<id>/disconnect/` | Revoke and delete credential |

## Env usage

The plugin runtime uses the backend-wide env contract:
- `PUBLIC_BACKEND_URL`
- `PLUGIN_OAUTH_SUCCESS_REDIRECT`
- `PLUGIN_OAUTH_FAILURE_REDIRECT`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- optional `MICROSOFT_CLIENT_ID`
- optional `MICROSOFT_CLIENT_SECRET`
- `SUPABASE_URL`
- optional `SUPABASE_JWT_AUDIENCE`

The Google-backed registry entries (`gmail`, `google_calendar`, `google_drive`, `google_contacts`) use:
- `client_id_env = "GOOGLE_CLIENT_ID"`
- `client_secret_env = "GOOGLE_CLIENT_SECRET"`

The Microsoft-backed registry entries (`outlook`, `outlook_calendar`) use:
- `client_id_env = "MICROSOFT_CLIENT_ID"`
- `client_secret_env = "MICROSOFT_CLIENT_SECRET"`

Those Microsoft settings default blank and are only required when Outlook plugins are used.

## Credential API behavior

Credential reads are redacted:
- `GET /plugins/credentials/`
- `GET /plugins/credentials/<id>/`

Those responses do not expose:
- `access_token`
- `refresh_token`

Credential writes still accept token fields through the write serializer:
- `POST /plugins/credentials/`
- `PUT /plugins/credentials/<id>/`
- `PATCH /plugins/credentials/<id>/`

## OAuth behavior

- The connect view returns an `auth_url`.
- The callback paths are:
  - `/plugins/oauth/callback/gmail/`
  - `/plugins/oauth/callback/google_calendar/`
  - `/plugins/oauth/callback/google_drive/`
  - `/plugins/oauth/callback/google_contacts/`
  - `/plugins/oauth/callback/outlook/`
  - `/plugins/oauth/callback/outlook_calendar/`
- The callback redirect URI is built from `PUBLIC_BACKEND_URL` when it is set.
- After the provider callback exchanges the code, the backend stores encrypted pending token data and redirects to `PLUGIN_OAUTH_SUCCESS_REDIRECT` with `completion_token=<opaque-token>`.
- The app must call `POST /plugins/oauth/finalize/` with bearer auth and that completion token before credentials are stored.
- The default app-return targets are `aiva://oauth/{plugin}/success` and `aiva://oauth/{plugin}/failure`, resolved with the callback plugin key.
- Static redirect overrides are supported, but plugin-aware values should include `{plugin}` so each integration can return to its own app route.
- Google should still be configured with the backend callback URL, not `aiva://...`.
- OAuth state is signed, time-limited, server-side, and one-time.
- `PluginOAuthStates` stores the initiating user/plugin for each nonce, pending callback token data, and finalize status.
- The public callback alone cannot create credentials; finalize requires the authenticated initiating Aiva user.
- Disconnect attempts provider revoke before deleting the local credential row.
- Google Drive support requires the Google Drive API to be enabled in Google Cloud.
- Google Contacts support requires the People API to be enabled in Google Cloud.
- Outlook support requires a Microsoft Entra app registration with the matching backend callback URLs.
- New plugins using the generic flow inherit the callback/finalize split and should not bypass it.

## CredentialService

`plugins/services/credentials.py` is the source of truth for:
- OAuth code exchange
- refresh-token flow
- active credential lookup
- token-data serialization for the orchestrator
- token persistence back into `PluginCredentials`
- OAuth state generation and validation
- provider account-id lookup through registry `account_id_endpoint` entries
- provider revoke

The Gmail tool does not refresh tokens itself. Refresh happens in `CredentialService` before credentials are injected into the tool.
