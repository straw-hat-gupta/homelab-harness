# Adding A New OAuth Plugin

This guide explains exactly what has to change in the current backend to add a **new user-connectable OAuth-backed plugin** that follows the same architecture and conventions as the existing integrations.

It is written against the live backend under:

- `/Users/samgupta/Github/Aiva/v2/backend`

This is **not** the guide for adding a tool-only integration. This is specifically for a plugin that:

- appears in `/plugins/registry/`
- can be connected by a user through `/plugins/oauth/connect/`
- completes OAuth through the public callback plus authenticated `/plugins/oauth/finalize/`
- ultimately stores credentials in `PluginCredentials`
- is usable by the planner/orchestrator through `ToolDef.plugin_id`

## Core Mental Model

The backend splits plugin support across two layers:

1. **Plugin/OAuth layer** in `plugins/`
   - defines what integrations exist
   - starts OAuth
   - handles the callback
   - stores pending callback token data
   - finalizes OAuth into stored credentials after authenticated app confirmation

2. **Tool layer** in `tools/`
   - defines what the agent can actually do with that integration
   - declares which stored credential should be injected

The join key across the whole system is one exact string:

- `registry key == Credentials.plugin == project.plugins key == ToolDef.plugin_id`

If those keys do not match exactly, the integration will look partially wired but will not behave correctly end to end.

## What Already Exists

These parts are generic and are supposed to be reused:

- [plugins/views.py](/Users/samgupta/Github/Aiva/v2/backend/plugins/views.py)
  - generic registry endpoint
  - generic OAuth start endpoint
  - generic OAuth callback endpoint
  - generic OAuth finalize endpoint
  - generic credential CRUD
- [plugins/models.py](/Users/samgupta/Github/Aiva/v2/backend/plugins/models.py)
  - `Credentials` model
  - `OAuthState` model for server-side one-time state, pending token data, and finalize state
- [plugins/services/credentials.py](/Users/samgupta/Github/Aiva/v2/backend/plugins/services/credentials.py)
  - generic code exchange
  - generic refresh
  - generic credential lookup and persistence
- [orchestrator/credentials.py](/Users/samgupta/Github/Aiva/v2/backend/orchestrator/credentials.py)
  - loads stored credential data for a tool
- [tools/registry.py](/Users/samgupta/Github/Aiva/v2/backend/tools/registry.py)
  - central tool registration
- [tools/apps.py](/Users/samgupta/Github/Aiva/v2/backend/tools/apps.py)
  - auto-discovers tool packages

Because those extension points already exist, a normal OAuth-backed plugin does **not** need:

- a new Django app
- a new Django model
- a new route
- a migration

Only add those if the provider truly needs data that the current `Credentials` model cannot represent.

## Files You Must Edit

### 1. `plugins/plugins/registry.py`

Edit:

- [plugins/plugins/registry.py](/Users/samgupta/Github/Aiva/v2/backend/plugins/plugins/registry.py)

This is the canonical plugin registry. Every new connectable plugin starts here.

Add one new entry to `PLUGIN_REGISTRY` with:

- plugin key
- `display`
- `contact_service`
- `auth_url`
- `token_url`
- `revoke_url`
- `scopes`
- `client_id_env`
- `client_secret_env`
- `extra_params`
- `redirect_path`

Example shape:

```python
"slack": {
    "display": "Slack",
    "contact_service": None,
    "auth_url": "...",
    "token_url": "...",
    "revoke_url": "...",
    "scopes": [...],
    "client_id_env": "SLACK_CLIENT_ID",
    "client_secret_env": "SLACK_CLIENT_SECRET",
    "extra_params": {...},
    "redirect_path": "/plugins/oauth/callback/slack/",
},
```

What this entry automatically enables:

- `/plugins/registry/` includes the plugin
- `/plugins/oauth/connect/` accepts the plugin key
- `/plugins/oauth/callback/<plugin_key>/` can resolve the provider config
- `project.plugins` can gate the plugin
- `CONTACT_SERVICES` updates automatically if `contact_service` is not `None`

### 2. `backend/settings.py` if the provider uses new secrets

Edit only when needed:

- [backend/settings.py](/Users/samgupta/Github/Aiva/v2/backend/backend/settings.py)

Important detail:

`CredentialService._setting()` reads from `django.conf.settings`, not directly from raw environment variables.

That means the registry values:

- `client_id_env`
- `client_secret_env`

must point to setting names that actually exist in `settings.py`.

If the new plugin reuses existing Google credentials:

- no settings change is required

If it uses a new provider:

add settings entries like:

```python
SLACK_CLIENT_ID = env("SLACK_CLIENT_ID")
SLACK_CLIENT_SECRET = env("SLACK_CLIENT_SECRET")
```

## Files You May Need To Edit

### 3. `plugins/services/credentials.py`

Edit as needed:

- [plugins/services/credentials.py](/Users/samgupta/Github/Aiva/v2/backend/plugins/services/credentials.py)

What is already generic:

- auth-code exchange
- refresh-token exchange
- active credential lookup
- token persistence
- revoke behavior when the provider fits the current pattern

What may need provider-specific code:

#### `fetch_account_id(plugin_key, access_token)`

Today this is generic for registry entries that define `account_id_endpoint`. Existing examples include Gmail, Google Drive, Google Contacts, Outlook Mail, and Outlook Calendar.

You need to decide whether the new plugin should:

- return `None` for `account_id`
- or fetch a stable account identifier

Use a real account id if the plugin naturally has one, such as:

- email
- workspace id
- tenant id
- account id

Reasons to implement it:

- cleaner UI label in credential listings
- multi-account disambiguation
- lets the planner target the correct account when multiple credentials exist

#### `revoke(creds)`

If the provider revoke endpoint or request shape differs from the current generic form, extend this function.

#### `exchange_code()` or `refresh_token()`

If the provider is not standard OAuth2 form-post compatible, add provider-specific behavior here.

Current repo convention:

- provider-specific credential behavior stays inline in `CredentialService`
- there is not a separate service file per provider

### 4. Docs and env contract files

If the plugin introduces new settings or setup steps, update:

- [README.md](/Users/samgupta/Github/Aiva/v2/backend/README.md)
- [plugins/README.md](/Users/samgupta/Github/Aiva/v2/backend/plugins/README.md)
- [docs/FEATURES.md](/Users/samgupta/Github/Aiva/v2/backend/docs/FEATURES.md)
- [docs/ENDPOINTS.md](/Users/samgupta/Github/Aiva/v2/backend/docs/ENDPOINTS.md)
- [docs/SETUP.md](/Users/samgupta/Github/Aiva/v2/backend/docs/SETUP.md)
- [docs/CHANGELOG.md](/Users/samgupta/Github/Aiva/v2/backend/docs/CHANGELOG.md)

## Folders And Files You Must Add

Add a new tool package under:

- `/Users/samgupta/Github/Aiva/v2/backend/tools/<tool_namespace>/`

Required files:

- `__init__.py`
- `api.py`

Usually add tests too:

- `tests.py` or `tests_<behavior>.py`

### `__init__.py`

Keep it minimal. Import `api.py` so registration side effects run.

Current convention:

```python
from .api import *  # or an import that causes registration
```

### `api.py`

This is the real implementation file. Match the style of:

- [tools/gmail/api.py](/Users/samgupta/Github/Aiva/v2/backend/tools/gmail/api.py)
- [tools/calendar/api.py](/Users/samgupta/Github/Aiva/v2/backend/tools/calendar/api.py)

Structure to follow:

1. imports
2. provider client/service builder
3. response transformation helpers
4. async tool functions
5. `register(ToolDef(...))` calls at the bottom

## Tool Naming And Registration Rules

### Folder name vs plugin key

The tool folder name does **not** have to equal the plugin registry key.

Current example:

- folder: `calendar`
- tool names: `calendar.*`
- plugin key: `google_calendar`
- `ToolDef.plugin_id = "google_calendar"`

So there are two names:

1. **tool namespace**
   - used in planner-visible tool names
2. **plugin key**
   - used for OAuth + credential identity

### Required `ToolDef` fields

For every tool that needs stored OAuth credentials:

- `requires_creds=True`
- `plugin_id="<registry key>"`

Other flags:

- `requires_confirmation=True` only for irreversible external side effects
- `requires_user_id=True` only if the tool truly needs backend user context

### Naming convention

Tool names should be stable and verb-oriented.

Examples:

- `slack.list_channels`
- `slack.post_message`
- `drive.search_files`
- `drive.create_document`

## Current Tool Implementation Style

If you want the new plugin to feel native to this repo, follow these conventions from Gmail and Calendar:

- provider client/service builder near the top
- blocking SDK calls wrapped in `asyncio.to_thread(...)`
- helper functions that normalize provider responses into backend-friendly dicts
- `logger.info(...)` on meaningful operations
- planner-facing parameter docs written in `params_schema`
- all `ToolDef` registrations grouped at the bottom of the file

Do not introduce a radically different structure unless the provider SDK truly forces it.

## How Planner And Executor Wiring Works

You do **not** need extra planner wiring if the plugin key is consistent.

The existing path already handles:

- filtering planner-visible tools by `project.plugins`
- filtering connected plugin/account context by enabled plugins
- loading credentials by `ToolDef.plugin_id`

Relevant files:

- [agent/views.py](/Users/samgupta/Github/Aiva/v2/backend/agent/views.py)
- [tools/registry.py](/Users/samgupta/Github/Aiva/v2/backend/tools/registry.py)
- [orchestrator/credentials.py](/Users/samgupta/Github/Aiva/v2/backend/orchestrator/credentials.py)

That means the new plugin becomes project-gatable automatically as soon as:

- the registry key exists
- the tool registrations use the same `plugin_id`

## Account ID Decision

You should make this decision explicitly for every new plugin.

### Option 1. Single-account plugin

- omit `account_id_endpoint` from the registry, so `fetch_account_id()` returns `None`
- credentials are stored with `account_id = NULL`

This is the simplest path.

### Option 2. Multi-account or labeled-account plugin

- add a registry `account_id_endpoint` when the provider can be handled by the generic HTTP/JSON lookup
- extend `fetch_account_id()` only when the provider needs custom behavior
- return a stable identifier

Use this when:

- users may connect multiple accounts
- the frontend should display which account is connected
- the planner may need account disambiguation

Default recommendation:

- if the provider naturally exposes a stable account identity, implement it
- do not leave the behavior accidental or ambiguous

## OAuth Security Invariant

The generic OAuth flow is intentionally split into two phases:

- the public provider callback exchanges the auth code and stores encrypted pending token data
- the authenticated app calls `POST /plugins/oauth/finalize/` with the deep-link `completion_token`
- credentials are written only when the authenticated user matches the user that started OAuth

Do **not** add plugin-specific OAuth flows that bypass this split. A public provider callback must not directly create `PluginCredentials`.

Security properties to preserve:

1. signed provider `state` contains only an opaque nonce
2. `PluginOAuthStates` stores initiating user, plugin, expiry, and pending encrypted token data
3. callback consumes state exactly once and returns only a completion token to the app
4. finalize requires bearer auth from the initiating user before saving credentials
5. finalize clears pending access/refresh tokens and invalidates the completion token

## Tests You Should Add

### Plugin/OAuth tests

Edit:

- [plugins/tests/test_plugins.py](/Users/samgupta/Github/Aiva/v2/backend/plugins/tests/test_plugins.py)

Minimum coverage:

- registry endpoint includes the new plugin
- connect endpoint returns a valid auth URL
- callback failure redirects correctly
- callback success stores a pending OAuth result and returns a success deep link with `completion_token`
- finalize stores a `Credentials` row with the correct plugin key
- refresh path works if the provider supports refresh tokens
- `account_id` behavior matches the provider design

### Tool tests

Add in:

- `/Users/samgupta/Github/Aiva/v2/backend/tools/<tool_namespace>/tests.py`

Minimum coverage:

- tool registrations exist in `_REGISTRY`
- `requires_creds`, `plugin_id`, and `requires_confirmation` are correct
- service/client builder uses the expected settings and token fields
- provider response transformation is correct
- important provider error paths surface correctly

### Optional agent-level tests

If the new plugin changes planner gating assumptions, add targeted tests in:

- [agent/tests/test_views.py](/Users/samgupta/Github/Aiva/v2/backend/agent/tests/test_views.py)

Useful cases:

- plugin disabled in `project.plugins`
- plugin enabled but not connected
- plugin connected and visible to the planner

## Files That Usually Do Not Need To Change

For a normal OAuth-backed plugin, you usually do **not** need to touch:

- `plugins/views.py`
- `plugins/urls.py`
- `plugins/models.py`
- migrations
- `orchestrator/credentials.py`
- `tools/registry.py`
- `tools/apps.py`

Those are already generic enough for the expected extension pattern.

Only change them if the new provider breaks the current assumptions.

## Practical Step-By-Step Checklist

1. Choose the final plugin key.
2. Add the registry entry in `plugins/plugins/registry.py`.
3. Add settings entries if the provider uses new secrets.
4. Extend `CredentialService` if the provider needs:
   - account-id lookup
   - custom token exchange
   - custom refresh
   - custom revoke
5. Add `tools/<tool_namespace>/`.
6. Create `__init__.py`.
7. Implement `api.py`.
8. Register all tools with correct `plugin_id`.
9. Add plugin tests.
10. Add tool tests.
11. Update docs and env contract.
12. Verify planner visibility, credential injection, and callback behavior end to end.

## Summary

To add another OAuth-backed plugin in this backend, the true required work is:

- one new registry entry
- optional provider-specific additions in `CredentialService`
- one new tool package under `tools/`
- tests
- docs/env updates

The architecture is intentionally generic, but not fully provider-agnostic. The plugin registry defines the integration, while the tool package defines what the agent can do with it. The key discipline is keeping the plugin key consistent everywhere and matching the Gmail/Calendar implementation style instead of introducing a new pattern.
