# Backend Features

High-level feature descriptions with implementation details. Use this as the authoritative reference for what the backend provides and how each feature works under the hood.

---

## Authentication

**What it does:** All API endpoints are protected by Supabase-issued JWTs. The backend verifies tokens locally without a network round-trip to Supabase on each request, then auto-creates or updates a local Django `User` row on first contact.

**Implementation:**
- `authentication/authentication.py` — `SupabaseAuthentication` DRF class. Decodes the `Authorization: Bearer <token>` header using `HS256` with `SUPABASE_JWT_SECRET`, validates `exp`, `iat`, `sub`, issuer, and optionally `aud`.
- `authentication/models.py` — `User` model keyed by required `supabase_uid` (the JWT `sub` claim). Email is synced from the JWT only for the matching Supabase UID when the incoming email is unclaimed.
- DRF `DEFAULT_AUTHENTICATION_CLASSES` is set to `SupabaseAuthentication` only — no session auth.
- Users are reconciled through a strict Supabase identity sync path: load by `supabase_uid`, create a row with that `supabase_uid` when it does not exist, and reject email conflicts instead of claiming email-only rows. The migration to require `supabase_uid` refuses to run while legacy `supabase_uid=NULL` rows exist, so those rows must be deleted or backfilled before deployment. No signup endpoint exists on this backend; account creation goes through Supabase directly.

**Env vars:** `SUPABASE_URL`, `SUPABASE_JWT_SECRET`, optional `SUPABASE_JWT_AUDIENCE`

---

## Projects

**What it does:** A `Project` is the top-level namespace for a user's work. Every agent conversation is scoped to a project. Projects carry metadata (name, description, active plugins) and a pending-plan field used by the orchestrator.

**Implementation:**
- `projects/models.py` — `Projects` model with `user` FK, `name`, `description`, `plugins` (JSONField), `activeContextFrom` (int), `pending_plan` (JSONField, null).
- `projects/views.py` — standard DRF CRUD views with ownership enforcement (`user=request.user` filter on all reads/writes).
- `projects/serializers.py` — camelCase serializer fields (`activeContextFrom`, `createdAt`).
- `pending_plan` is read and written by `agent/pending_plan.py` during orchestration; it stores the in-progress plan when user confirmation is required before execution.

**Routes:** `GET/POST /projects/`, `GET/PUT/PATCH/DELETE /projects/<id>/`

---

## Agent / Orchestrator

**What it does:** The core of the backend. Accepts a natural-language prompt, produces a multi-step execution plan via an LLM, optionally asks the user for confirmation, then executes the plan step-by-step using registered tools. Returns a natural-language response.

**Implementation — request flow:**

1. `agent/views.py` `agent_view` parses `prompt`, `project_id`, `dry_run` from the JSON body and calls `run_prompt()`.
2. `run_prompt()` in `agent/views.py`:
   - Loads the conversation context (`agent/chat_context.py` → `ProjectContext` DB rows).
   - Loads the user's persistent memories (`UserMemory` rows via `_load_user_memories(user)`).
   - Calls `_get_enabled_plugins(project)` to read `project.plugins` (`{"gmail": true, "google_calendar": false, "google_drive": true, "google_contacts": true, "outlook": false}`). Empty dict = no restriction (`None`).
   - Passes `enabled_plugins` to `get_schemas_for_planner()` to filter available tool schemas; also filters `connected_plugins` to the enabled set. Tools with `plugin_id=None` (processing_llm, weather, contacts, web, memory) are always included.
   - Checks for a stored pending plan (`agent/pending_plan.py` → `Projects.pending_plan` JSONField).
   - If a pending plan exists: calls `detect_intent()` to determine confirm / cancel / modify, then acts accordingly.
   - If no pending plan: calls `_is_capabilities_query()` for "what can you do?" short-circuits; otherwise calls `plan()`.
   - Before executing or saving any plan: calls `_validate_plan_plugins(plan, enabled_plugins)` — raises `UnknownToolError` if any step uses a tool from a disabled plugin.
   - If the new plan requires confirmation and `dry_run=False`: saves it to `pending_plan`, returns a summary with "Shall I proceed?".
   - If `dry_run=True` or no confirmation required: calls `execute()` immediately.
3. `orchestrator/orchestrator.py` `execute()`:
   - Iterates plan steps in order. Each step has a tool name, parameters, and output variable.
   - Resolves credential injection for tools that `requires_creds=True`.
   - Substitutes prior-step outputs into current-step parameters (variable references like `$step_1_output`).
   - If `dry_run=True`, skips `requires_confirmation=True` steps with a placeholder.
   - Calls the tool function and stores the result keyed by `output_var`.
   - Returns the value of `final_output_var` after all steps complete.

**Confirmation flow:** Plans containing any step with `requires_confirmation=True` (for example Gmail send/trash actions, calendar create/update/delete actions, Outlook send/reply actions, and contact deletion) are held in `Projects.pending_plan` until the user explicitly confirms. `detect_intent()` uses token-set short-circuit matching first (`_CONFIRM_TOKENS` / `_CANCEL_TOKENS`), then an LLM call if ambiguous.

**Dry-run mode:** `"dry_run": true` in the request body bypasses confirmation gating and skips destructive steps. The response includes a `"dry_run": true` flag and a notice appended to the text.

**Reset:** `DELETE /agent/reset/<project_id>/` clears the `ProjectContext` conversation rows and nulls `pending_plan` for the project.

**Error handling:**
- `orchestrator/exceptions.py` defines `ToolExecutionError`, `UnknownToolError`, `ToolValidationError`.
- `ToolExecutionError` triggers a `call_processing_llm` call to produce a user-friendly explanation; falls back to a generic message. HTTP 500 is preserved.
- All error responses include an `error_code` field.

**Key files:** `agent/views.py`, `orchestrator/orchestrator.py`, `orchestrator/exceptions.py`, `tools/registry.py`

---

## Planner

**What it does:** Translates a natural-language prompt (plus conversation history and connected-plugin context) into a typed JSON execution plan. Also handles intent classification (confirm / cancel / modify) for pending plans and plan revision.

**Implementation:**
- `planner/planner.py` — `plan()`, `revise_plan()`, `detect_intent()` all call the OpenAI chat completion API (`PLANNER_MODEL`, default `gpt-4o-mini`).
- The system prompt includes: all registered tool schemas, connected-plugin list, and explicit instruction not to plan steps for unconnected plugins. If a required plugin is missing, the planner generates a single `processing_llm` step telling the user to connect it in Settings → Plugins.
- `plan()` returns a `Plan` (list of typed `Step` objects from `planner/schemas.py`).
- `detect_intent()` checks `_CONFIRM_TOKENS` / `_CANCEL_TOKENS` sets first (zero-cost short-circuit), then calls the LLM with `max_tokens=10` if the message is ambiguous.
- Every `plan()` / `revise_plan()` / `detect_intent()` LLM call persists input/output token counts to `PlannerUsage` (per-user, per-call, timestamped).
- All calls respect `PLANNER_TIMEOUT` (default 60 s).
- `connected_plugins` and `user_id` are threaded into every planner call from `agent/views.py` via `orchestrator/credentials.py` `get_connected_plugins()`.

**Env vars:** `PLANNER_MODEL`, `PROCESSING_LLM_MODEL`, `OPENAI_KEY`, `PLANNER_TIMEOUT`

---

## Conversation Context

**What it does:** Maintains per-project LLM conversation history across requests so the agent has memory of earlier turns within a session. The same `ProjectContext` table also serves the `/project-context/` UI transcript API — both writers use append-only inserts, so neither overwrites the other's rows.

**Implementation:**
- `agent/chat_context.py` — `get_ctx()` returns a `ChatContext` object backed by `context/models.py` `ProjectContext` DB rows (one row per message, keyed by `user_id` + `project_id`).
- Each `ProjectContext` row stores `role` (`user` / `assistant`), `content`, and a monotonically increasing `sequence` number.
- `DbContextStore.save()` is **append-only**: new messages are inserted at `MAX(sequence)+1` inside a `select_for_update()` transaction (same pattern as `context/views.py`), so agent writes and frontend writes never collide.
- **Pruning via `activeContextFrom`**: when the token budget is exceeded, `_prune()` advances `Projects.activeContextFrom` to the sequence of the next surviving message instead of deleting rows. The DB retains the full transcript; `load()` applies `sequence >= activeContextFrom` to return only the active LLM window.
- `ChatContext` tracks `_sequences` (parallel list, `None` = not yet saved) and `_active_from` (pending `activeContextFrom` update) so each `add_message()` save is a minimal append + optional cursor update.
- Context is pruned to a token budget using `tiktoken` (`cl100k_base` encoding) with a character-count heuristic fallback. Oldest messages are dropped first (system/tool messages prioritised for dropping).
- `DELETE /agent/reset/<project_id>/` clears all rows **and** resets `activeContextFrom = 0` so subsequent low-sequence inserts are visible on the next load.
- History survives container restarts because it is DB-backed.

---

## Plugin OAuth & Credentials

**What it does:** Manages the OAuth lifecycle for third-party integrations. The live registry currently includes `gmail`, `google_calendar`, `google_drive`, and `google_contacts`, and the plumbing supports additional OAuth-backed plugins.

**Implementation:**
- `plugins/plugins/registry.py` — canonical plugin registry. Each entry defines `plugin_id`, `display` label, OAuth scopes, env var names for `client_id` / `client_secret`, and `contact_service` (the label used in `ContactConnection.service`, or `None`). The module-level `CONTACT_SERVICES` frozenset is derived from this registry and used by `contacts/views.py` for connection validation.
- `plugins/models.py` — `PluginCredentials` model stores encrypted `access_token` / `refresh_token`, `expires_at`, `account_id`, and `plugin` per user.
- `plugins/models.py` — `OAuthState` model stores one-time OAuth state nonces, initiating user, plugin, expiry, consumption timestamp, encrypted pending token data, and finalize status.
- `plugins/views.py`:
  - `POST /plugins/oauth/connect/` returns a signed `auth_url` for the user to open.
  - `GET /plugins/oauth/callback/<plugin_key>/` receives the Google redirect, exchanges the auth code, stores a pending OAuth result, and redirects to `PLUGIN_OAUTH_SUCCESS_REDIRECT` with a `completion_token`.
  - `POST /plugins/oauth/finalize/` is the authenticated app-side completion step that verifies the same Aiva user started OAuth before writing `PluginCredentials`.
- `plugins/services/credentials.py` `CredentialService`:
  - Handles code exchange, token refresh, account-id lookup through each plugin registry entry's `account_id_endpoint`, one-time state generation/validation, pending OAuth result storage, authenticated OAuth finalization, and provider revoke.
  - Credential reads are redacted — `access_token` and `refresh_token` are never returned to API clients.
- `orchestrator/credentials.py` `get_connected_plugins()` — queries active `PluginCredentials` for a user and returns the set of connected plugin IDs (used by the planner and agent view).
- Google-backed plugins currently reuse `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`; Google Drive also requires the Google Drive API to be enabled in Google Cloud.
- Microsoft-backed plugins (`outlook`, `outlook_calendar`) are present in the registry and require `MICROSOFT_CLIENT_ID` / `MICROSOFT_CLIENT_SECRET` values when those plugins are used.

**Env vars:** `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, optional `MICROSOFT_CLIENT_ID`, optional `MICROSOFT_CLIENT_SECRET`, `PUBLIC_BACKEND_URL`, `PLUGIN_OAUTH_SUCCESS_REDIRECT`, `PLUGIN_OAUTH_FAILURE_REDIRECT`

---

## Gmail Tools

**What it does:** Exposes Gmail read, search, draft, send, pagination, and attachment tools to the planner. Read/search operations require user confirmation only for destructive send actions.

**All registered tools** (`tools/gmail/api.py`):

| Tool | Description | Confirmation |
|---|---|---|
| `gmail.search_emails` | Keyword search (OR-combined), optional `hours_ago` filter | No |
| `gmail.get_unread_emails` | Unread inbox, optional `hours_ago` filter | No |
| `gmail.get_sent_emails` | Sent emails, optional `hours_ago` filter | No |
| `gmail.get_starred_emails` | Starred emails, optional `hours_ago` filter | No |
| `gmail.get_label_emails` | Emails by label name, optional `hours_ago` filter | No |
| `gmail.get_next_page` | Next page of the most recent Gmail query (cursor-based) | No |
| `gmail.get_drafts` | Email drafts list | No |
| `gmail.send_email` | Send a new plain-text email (to, subject, body, cc, bcc, reply_to) | **Yes** |
| `gmail.send_draft` | Send an existing draft by `draft_id` | **Yes** |
| `gmail.get_attachment` | Fetch attachment content by `msg_id` + `attachment_id` | No |
| `gmail.trash_email` | Move a message to Trash by `msg_id` | **Yes** |
| `gmail.mark_read` | Remove the UNREAD label from a message | No |
| `gmail.mark_unread` | Add the UNREAD label to a message | No |
| `gmail.add_label` | Apply a label to a message by label name | No |
| `gmail.remove_label` | Remove a label from a message by label name | No |
| `gmail.create_draft` | Save a composed email as a draft without sending | No |

**Pagination implementation:** All fetch tools (except `get_drafts` and `get_attachment`) accept `user_id` and store a `next_page_token` in Django cache (1-hr TTL, keyed by `user_id`). `gmail.get_next_page` reads the stored cursor and fetches the next page; the cursor is cleared when no further pages exist.

**Credential flow:** All tools call `_build_service()` with the user's token data from `PluginCredentials`. Token refresh is handled by `CredentialService` before injection.

---

## Google Calendar Tools

**What it does:** Lets the agent list, create, update, delete, and check free/busy blocks on the user's Google Calendar. Uses its own `google_calendar` credential row but the same Google OAuth app settings as the other Google-backed plugins.

**All registered tools** (`tools/calendar/api.py`):

| Tool | Params | Description |
|---|---|---|
| `calendar.list_events` | `max_results`, `time_min`, `time_max`, `query`, `calendar_id` | List upcoming events with optional time range and free-text filter |
| `calendar.create_event` | `summary`, `start`, `end`, `description`, `location`, `attendees`, `calendar_id` | Create an event; start/end accept RFC3339 datetime or date string |
| `calendar.update_event` | `event_id`, `summary`, `start`, `end`, `description`, `location`, `calendar_id` | Patch an existing event (only supplied fields are changed) |
| `calendar.delete_event` | `event_id`, `calendar_id` | Delete an event by ID |
| `calendar.get_free_busy` | `time_min`, `time_max`, `calendar_id` | Return busy slots within a time range |
| `calendar.list_calendars` | none | List calendars available to the user |

**Note:** Calendar tools load credentials from `PluginCredentials` rows where `plugin="google_calendar"`. The plugin has its own OAuth flow and callback path, even though it reuses `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`.

---

## Google Drive Tools

**What it does:** Lets the agent inspect Google Drive file metadata and read text-like file content through a read-only Drive credential. It does not create, update, move, or delete files.

**All registered tools** (`tools/drive/api.py`):

| Tool | Params | Description |
|---|---|---|
| `drive.list_files` | `max_results`, `folder_id` | List recent non-trashed files and folders accessible to the user |
| `drive.search_files` | `query`, `max_results`, `folder_id` | Search Drive files by name |
| `drive.get_file_metadata` | `file_id` | Return detailed metadata for one file or folder |
| `drive.read_file` | `file_id`, `mime_type` | Read supported file content, including Google Docs export where supported |

**Returned metadata shape:** `id`, `name`, `mime_type`, `created_time`, `modified_time`, `size`, `owners`, `web_view_link`, `trashed`, `starred`, `parents`

**Implementation notes:**
- Uses the Google Drive API v3 with scope `https://www.googleapis.com/auth/drive.readonly`
- Loads credentials from `PluginCredentials` rows where `plugin="google_drive"`
- Stores `account_id` as the Drive user's email address via the Drive About API
- Does **not** create files, update files, move files, or delete files in this version

---

## Google Contacts Tools

**What it does:** There are two contact tool families. `contacts.*` manages the backend's local contact store. `google_contacts.*` reads Google Contacts through the Google People API and can sync selected people into the local contact store.

**All registered tools** (`tools/contacts/api.py`):

| Tool | Params | Description |
|---|---|---|
| `contacts.search` | `query`, `limit` | Search contacts by name, alias, or email fragment |
| `contacts.create` | `first_name`, `last_name`, `alias`, `email` | Add a new contact |
| `contacts.update` | `contact_id`, `first_name`, `last_name`, `alias`, `email` | Update fields on an existing contact |
| `contacts.delete` | `contact_id` | Delete a contact |

**Implementation:** Contacts are stored in the backend DB (`contacts/models.py`) — not synced with Google People API. The tools call `contacts/services.py` directly.

**Google Contacts tools** (`tools/google_contacts/api.py`):

| Tool | Params | Description |
|---|---|---|
| `google_contacts.list` | `max_results` | List people from Google Contacts |
| `google_contacts.search` | `query`, `max_results` | Search Google Contacts |
| `google_contacts.sync` | `max_results` | Import/update Google Contacts into the backend local contacts table |

**Implementation:** Google Contacts uses the separate `google_contacts` plugin credential, requires the People API to be enabled in Google Cloud, and loads credentials from `PluginCredentials` rows where `plugin="google_contacts"`.

---

## Outlook Tools

**What it does:** Lets the agent read/search/send Outlook email and list/create/update/delete Outlook calendar events through Microsoft Graph.

**Mail tools** (`tools/outlook/api.py`, `plugin_id="outlook"`):

| Tool | Description | Confirmation |
|---|---|---|
| `outlook.get_unread_emails` | Fetch unread Outlook messages | No |
| `outlook.get_emails` | Fetch recent messages from inbox, sent items, drafts, or deleted items | No |
| `outlook.search_emails` | Search Outlook mail by keyword/KQL-style query | No |
| `outlook.send_email` | Send a plain-text Outlook email | **Yes** |
| `outlook.reply_email` | Reply in-thread to an Outlook message | **Yes** |

**Calendar tools** (`tools/outlook/api.py`, `plugin_id="outlook_calendar"`):

| Tool | Description | Confirmation |
|---|---|---|
| `outlook_calendar.list_events` | List Outlook calendar events | No |
| `outlook_calendar.create_event` | Create an Outlook calendar event | **Yes** |
| `outlook_calendar.update_event` | Update an Outlook calendar event | **Yes** |
| `outlook_calendar.delete_event` | Delete an Outlook calendar event | **Yes** |
| `outlook_calendar.get_free_busy` | Return busy slots within a time range | No |

**Implementation:** Both Outlook plugin registry entries point at Microsoft OAuth and Microsoft Graph. They require the Microsoft client ID/secret to be available through Django settings before OAuth connect can succeed.

---

## Weather Tools

**What it does:** Lets the agent answer weather queries using OpenWeatherMap. No OAuth required — uses an API key.

**All registered tools** (`tools/weather/api.py`):

| Tool | Params | Description |
|---|---|---|
| `weather.get_current_weather` | `city` | Current conditions for a city name (optionally with country code) |
| `weather.get_weather_forecast` | `city`, `days` | Multi-day forecast (up to 16 days) |
| `weather.get_weather_by_coordinates` | `lat`, `lon` | Current conditions by lat/lon |

**Env vars:** `OPENWEATHER_API_KEY`

---

## Web Search Tool

**What it does:** Searches the web via the Tavily API and returns ranked results with titles, URLs, and content snippets. Always available to the planner (no plugin connection required).

**Implementation:** `tools/web/api.py` — POSTs to `https://api.tavily.com/search` with `search_depth=basic`. Results are capped at 10. When `include_answer=true`, Tavily returns an AI-synthesized direct answer alongside the result list.

**All registered tools** (`tools/web/api.py`):

| Tool | Params | Description |
|---|---|---|
| `web.search` | `query`, `max_results`, `include_answer` | Search the web; returns `{"answer": str\|null, "results": [{title, url, content, score}]}` |

**Env vars:** `TAVILY_API_KEY`

---

## Persistent Memory

**What it does:** Stores user-specific facts (preferences, name, location, ongoing goals) that persist across conversations. Memories are injected into every planner system prompt so the planner can personalise its responses without asking the user to re-state the same facts.

**Implementation:**
- `agent/models.py` — `UserMemory` model: `user` FK, `key` (max 255 chars), `value` (text), `source` (`manual` | `agent`), `created_at`, `updated_at`. `unique_together = ('user', 'key')` — one value per key per user.
- `agent/views.py` `_load_user_memories(user)` — loads all memories for the request user before each planner call.
- `planner/planner.py` `_build_system()` — accepts a `memories` list and renders it as a `- key: value` block in the system prompt (rule 13 instructs the planner to use memories as ground truth and call `memory.save` / `memory.delete` when the user asks).
- `planner/planner.py` `_plan_cache_key()` — memories are hashed into the cache key so different memory states produce different cache entries.

**Memory tools** (`tools/memory/api.py`):

| Tool | Params | Description |
|---|---|---|
| `memory.save` | `key`, `value` | Upsert a memory by key; always called with source=`agent` |
| `memory.delete` | `key` | Delete a memory by key |

Both tools have `requires_user_id=True` and `requires_confirmation=False` — the orchestrator injects `user_id` automatically; no user approval is needed.

**REST CRUD** (for frontend / manual management):

| Method | Route | Description |
|---|---|---|
| `GET` | `/agent/memory/` | List all memories for the authenticated user |
| `POST` | `/agent/memory/` | Upsert a memory by key (source = `manual`) |
| `PUT` | `/agent/memory/<id>/` | Update value/key on a specific memory |
| `DELETE` | `/agent/memory/<id>/` | Delete a specific memory |

---

## Saved Workflows

**What it does:** Lets users store a validated execution plan (Plan JSON) and replay it later via a single API call — no LLM re-planning needed. Plans are deterministic (same steps, same tool params every run) and cheap (zero planner tokens). Two creation paths: generate a plan via the agent then save it, or build one manually using the tool-schemas endpoint.

**Model:** `workflows/models.py` — `SavedWorkflow` with `user` FK, `name`, `description` (optional), `plan` (JSONField storing the `Plan` schema), `input_schema` (optional JSON array for `$input.*` runtime inputs), optional `project` FK, and timestamps.

**Plan schema** (`planner/schemas.py`):
```json
{
  "steps": [
    {"id": "s1", "tool": "web.search", "params": {"query": "..."}, "output_var": "results"},
    {"id": "s2", "tool": "processing_llm", "params": {"instruction": "...", "data": "$results"}, "output_var": "final"}
  ],
  "final_output_var": "final",
  "summary": "Search the web and summarise results"
}
```

**Validate endpoint:** `POST /workflows/validate/` validates a plan and optional `input_schema` without saving it.

**Run endpoint:** `POST /workflows/<id>/run/` calls `workflows.runner.run_saved_workflow(...)`. The runner validates the stored plan, validates/resolves `inputs` against `input_schema`, builds workflow initial context (`project_system_prompt` and `input`), then calls `orchestrator.execute(plan, user_id)` — the same code that runs agent plans, including credential injection, variable resolution, and retry logic. The endpoint has no separate run mode or confirmation request body; it executes saved workflows the same way the saved-workflow endpoint did before.

**Tool schemas endpoint:** `GET /tools/` returns registered tool schemas (name, display name, description, plugin ID, params) so a frontend step-builder can render available tools and their parameter definitions. Plugin-backed tools are filtered by the user's active credentials.

**REST CRUD:**

| Method | Route | Description |
|---|---|---|
| `GET` | `/tools/` | Return tool schemas for the frontend builder |
| `GET` | `/workflows/` | List all saved workflows for the authenticated user |
| `POST` | `/workflows/` | Create a workflow — requires `name` and a valid `plan` object |
| `POST` | `/workflows/validate/` | Validate a plan and input schema without saving |
| `GET` | `/workflows/<id>/` | Retrieve one workflow |
| `PUT` | `/workflows/<id>/` | Update `name`, `description`, `plan`, `input_schema`, or `project_id` (partial OK) |
| `DELETE` | `/workflows/<id>/` | Delete |
| `POST` | `/workflows/<id>/run/` | Execute the stored plan directly; accepts optional `{"inputs": {...}}` |

**Key files:** `workflows/models.py`, `workflows/views.py`, `workflows/runner.py`, `workflows/migrations/0001_initial.py`

---

## Scheduled Runs

**What it does:** Lets users run an existing saved workflow on a cron schedule. Scheduled runs reuse the saved workflow plan exactly as stored, so recurring execution does not re-plan with the LLM. V1 stores execution history in the backend DB and does not send push/email notifications.

**Model:** `workflows/models.py`

- `ScheduledRun` stores owner, saved workflow, display name, cron expression, IANA timezone, enabled flag, `next_run_at`, last status, last error, and timestamps.
- `ScheduledRunExecution` stores each queued/running/finished attempt with status, start/end timestamps, result, error, Celery task ID, and creation time.

**Runtime:** Celery Beat runs `workflows.dispatch_due_scheduled_runs` every minute. The dispatcher finds enabled schedules whose `next_run_at <= now`, creates queued execution rows, advances `next_run_at`, and enqueues `workflows.run_scheduled_run` jobs. Celery workers validate that the saved workflow still has a valid plan and known tools, then execute it through `workflows.runner.run_saved_workflow(...)`. Redis is the Celery broker.

**Confirmation behavior:** Scheduled runs execute the saved workflow exactly as stored. Tools marked `requires_confirmation=True` can be scheduled and will execute automatically when the schedule is due.

**REST CRUD:**

| Method | Route | Description |
|---|---|---|
| `GET` | `/scheduled-runs/` | List scheduled runs for the authenticated user |
| `POST` | `/scheduled-runs/` | Create a schedule for an owned saved workflow |
| `GET` | `/scheduled-runs/<id>/` | Retrieve one scheduled run |
| `PUT` | `/scheduled-runs/<id>/` | Update `workflow_id`, `name`, `cron`, `timezone`, or `enabled` |
| `DELETE` | `/scheduled-runs/<id>/` | Delete a scheduled run and its execution history |
| `POST` | `/scheduled-runs/<id>/run-now/` | Queue one immediate execution |
| `GET` | `/scheduled-runs/<id>/executions/` | List execution history |

**Runtime requirement:** API access only needs the web process. Actual scheduled execution requires web, Celery worker, Celery Beat, and Redis to be running.

**Key files:** `workflows/models.py`, `workflows/scheduling.py`, `workflows/runner.py`, `workflows/tasks.py`, `workflows/scheduled_views.py`, `backend/celery.py`

---

## Processing LLM Tool

**What it does:** A special internal tool that lets the planner generate direct text responses without calling any external API. Used for greetings, explanations, capability queries, and "plugin not connected" messages.

**Implementation:** `tools/processing_llm/tool.py` — calls `PROCESSING_LLM_MODEL` (default `gpt-4o-mini`) with a system prompt, the conversation context, and an `instruction` parameter from the plan step. The model's response becomes the step output and eventually the agent's final response.

**When the planner uses it:**
- Prompts that need no tools (e.g. "hello", "explain what you can do")
- When a required plugin is not connected — produces a message directing the user to Settings → Plugins
- When a tool execution fails and `ToolExecutionError` is caught — produces a natural-language error explanation

---

## Tasks

**What it does:** A DB-backed task/subtask layer for project tasks. It has explicit CRUD endpoints, and `/agent/` also creates lightweight execution records for non-dry-run plans that have a `project_id`.

**Implementation:**
- `tasks/models.py` — `Task` (with `dependency_requirement`, `confirmation_requirement`, `confirmation_status`, `result`) and `SubTask` models.
- `tasks/views.py` — DRF CRUD views scoped to `project_id`.
- `agent/views.py` — creates a `Task(status="running")` and one `SubTask` per plan step before immediate or confirmed execution when `project_id` is supplied and `dry_run=false`; marks the task `completed` or `failed` after orchestrator execution.
- Dry runs and confirmation prompts do not create task records. Confirmation-required actions create task records only after the user confirms.

**Routes:** `GET/POST /tasks/<projectId>/`, `GET/DELETE /tasks/<projectId>/<taskId>/`

---

## Project Context (UI Transcript API)

**What it does:** A DB-backed transcript store for per-project conversation history. The agent uses this table as its conversation buffer, and the frontend can also list, append user-authored rows, clear, or trim the transcript.

**Implementation:**
- `context/models.py` `ProjectContext` — rows with `role`, `content`, `sequence`, `createdAt`, scoped to a project.
- `context/views.py` — list, append, clear, and trim endpoints.
- `agent/chat_context.py` — appends agent user/assistant turns to the same table and advances `Projects.activeContextFrom` when pruning the LLM-visible window.
- Client `POST /project-context/<id>/` writes are limited to `role="user"` and `content` up to 10,000 characters. Backend-owned roles such as `assistant`, `system`, and `tool` remain backend-created only.

**Routes:** `GET/POST /project-context/<id>/`, `DELETE /project-context/<id>/clear/`, `POST /project-context/<id>/trim/`

---

## Contacts (DB App)

**What it does:** Stores and manages the user's local contact list in the backend database. Exposed as a REST API and also used internally by the Contacts orchestrator tools.

**Implementation:**
- `contacts/models.py` — `Contact` model with `first_name`, `last_name`, `alias`, `email`, `user` FK.
- `contacts/views.py` — DRF CRUD views with ownership enforcement.
- `contacts/services.py` — service layer used by both the REST API and the orchestrator tools.

**Routes:** `GET/POST /contacts/`, `GET/PUT/PATCH/DELETE /contacts/<id>/`

---

## Token Usage Tracking

**What it does:** Records input/output token counts for every planner LLM call, enabling cost attribution and future per-user caps.

**Implementation:**
- `agent/models.py` `PlannerUsage` — fields: `user` FK, `call_type` (`plan` / `revise` / `intent`), `input_tokens`, `output_tokens`, `model`, `created_at`.
- Written after every `plan()`, `revise_plan()`, and `detect_intent()` call. Write failure is a no-op (does not affect the agent response).
- No API endpoint exposes this data yet.
