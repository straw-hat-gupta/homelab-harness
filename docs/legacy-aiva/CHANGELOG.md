# Backend Changelog

## 2026-06-25 — Backend flow and env documentation refresh

### Summary
Updated backend reference docs to match the current live code paths for OAuth finalize, plugin registry keys, tool packages, task execution records, saved workflows, scheduled runs, and optional Microsoft OAuth settings.

### Files changed
- `docs/BACKEND_FLOWS.md` — refreshed agent, OAuth, saved-workflow, scheduled-run, storage, tool visibility, and error flows.
- `docs/ENDPOINTS.md` — updated plugin registry keys and Google Drive scope examples.
- `docs/FEATURES.md` — updated Drive read behavior, Outlook tools, Google Contacts tools, workflow input schema, and task execution behavior.
- `docs/ADDING_OAUTH_PLUGIN.md`, `plugins/README.md`, `docs/SETUP.md`, `README.md`, `.env.example` — aligned OAuth finalize and env setup guidance.
- `backend/settings.py` — added optional `MICROSOFT_CLIENT_ID` and `MICROSOFT_CLIENT_SECRET` settings used by the existing Outlook registry entries.

### Behavior changes
- No existing required setting changed.
- Outlook OAuth registry entries can now read Microsoft client credentials from Django settings when those optional env vars are provided.

---

## 2026-06-22 — Scheduled workflows can include confirmation-required tools

### Summary
Removed the v1 restriction that blocked scheduled runs from using saved workflows containing `requires_confirmation=True` tools.

### Files changed
- `workflows/scheduling.py` — schedule validation still checks workflow ownership, plan shape, and tool names, but no longer rejects confirmation-required tools
- `workflows/tests/test_scheduled_runs.py` — updated validation, API, and worker coverage for scheduling confirmation-required workflows
- `docs/ENDPOINTS.md`, `docs/FEATURES.md`, `docs/CHANGELOG.md`, `ROADMAP.md` — updated scheduled-run behavior docs

### Behavior changes
- `POST /scheduled-runs/` can now create schedules for workflows that contain tools such as `gmail.send_email`.
- Celery scheduled executions now call the shared saved-workflow runner for confirmation-required workflows instead of failing before execution.
- Scheduled runs execute the saved workflow exactly as stored, so any external side effects in that workflow can happen automatically when the schedule is due.
- Scheduled `run-now` and recurring dispatch now mark executions failed with `queue_unavailable` when Redis/Celery enqueue fails instead of leaving rows stuck in `queued` or raising a generic 500.
- OAuth app-return defaults are now plugin-aware: `aiva://oauth/{plugin}/success` and `aiva://oauth/{plugin}/failure`. Static overrides still work.
- OAuth callbacks now preserve an existing refresh token when the provider returns a new access token without a new refresh token.
- Tool tests now live under the same top-level Django app as their implementations, for example `tools.drive.tests`, instead of legacy `orchestrator.tools.*` module paths.
- Weather tool HTTP calls now pass an explicit 15-second timeout to OpenWeatherMap, preventing stalled external requests from hanging agent/workflow execution indefinitely.
- Gmail, Calendar, Drive, and Google Contacts service builders now use a shared `tools/google_http.py` AuthorizedHttp transport with an explicit 15-second timeout instead of relying on implicit Google client defaults.
- `/project-context/<id>/` POST now accepts only client-created `user` rows and rejects `content` longer than 10,000 characters. Backend-owned transcript roles remain internal-only.
- Credential token decrypt failures now fail closed by default. Plaintext fallback requires `CREDENTIAL_ENCRYPTION_ALLOW_PLAINTEXT_FALLBACK=true` and logs a warning for controlled legacy migration windows.
- Supabase JWT audience verification is now always enforced, defaulting `SUPABASE_JWT_AUDIENCE` to `authenticated` instead of disabling `verify_aud` when blank.
- OAuth connect now creates a server-side one-time `PluginOAuthStates` nonce and signs only that opaque nonce into provider `state`; callbacks reject expired, replayed, missing, or plugin-mismatched state before token exchange.
- OAuth callback completion now uses an authenticated finalize step: the public provider callback stores encrypted pending token data and redirects with `completion_token`, while `POST /plugins/oauth/finalize/` verifies the initiating user before writing `PluginCredentials`.

---

## 2026-06-22 — Shared saved-workflow runner

### Summary
Consolidated manual saved-workflow execution and scheduled saved-workflow execution through one shared runner service. `workflows.runner.run_saved_workflow(...)` now owns plan validation, workflow initial context, orchestrator invocation, and structured error mapping.

### Files changed
- `workflows/runner.py` — new shared execution service and `WorkflowRunResult`
- `workflows/views.py` — `/workflows/<id>/run/` now delegates to the shared runner
- `workflows/tasks.py` — scheduled Celery worker path now delegates to the shared runner
- `agent/tests/test_workflows.py`, `workflows/tests/test_runner.py`, `workflows/tests/test_scheduled_runs.py` — coverage for runner behavior and caller wiring
- `docs/ENDPOINTS.md`, `docs/FEATURES.md` — documented shared runner behavior

### Behavior changes
- Manual `/workflows/<id>/run/` behavior remains simple: no run mode, no `confirmed` request body, and no `dry_run` request body.
- Manual workflow runs and scheduled workflow runs now share the same workflow execution helper instead of duplicating plan validation and orchestrator calls.
- Scheduled workflow validation lives outside the runner and checks schedule fields, ownership, plan shape, and tool names.

---

## 2026-06-22 — Scheduled workflow runs

### Summary
Added scheduled recurring runs for saved workflows. A `ScheduledRun` points at an existing `SavedWorkflow` and stores cron/timezone configuration. Celery Beat dispatches due schedules every minute, Celery workers execute the saved workflow through the existing orchestrator path, and each attempt is persisted as a `ScheduledRunExecution`.

V1 stores results in the database only. Push/email delivery is not implemented. Workflows containing confirmation-required tools can be scheduled and will execute automatically when due.

### Files changed
- `workflows/models.py` — added `ScheduledRun`, `ScheduledRunExecution`, cron validation, timezone validation, and next-run calculation helpers
- `workflows/migrations/0002_scheduled_runs.py` — creates scheduled run and execution tables
- `workflows/scheduling.py` — shared workflow schedulability validation and initial-context helper
- `workflows/tasks.py` — Celery dispatcher and worker task implementation
- `workflows/scheduled_views.py` — authenticated scheduled-run CRUD, run-now, and execution-history endpoints
- `backend/celery.py`, `backend/__init__.py`, `backend/settings.py` — Celery app wiring and beat schedule
- `entrypoint.sh` — honors `RUN_MIGRATIONS=false` so worker/beat containers do not run migrations
- `docker-compose.yml`, `docker-compose.dev.yml`, `compose.image.yaml` — Redis, worker, and beat services
- `requirements.txt` — added `celery` and `croniter`
- `.env.example`, `README.md`, `ROADMAP.md`, `docs/ENDPOINTS.md`, `docs/FEATURES.md`, `docs/SETUP.md` — documentation and env-contract updates

### Endpoints added
| Method | Path | Description |
|---|---|---|
| `GET` | `/scheduled-runs/` | List scheduled runs |
| `POST` | `/scheduled-runs/` | Create a scheduled run for an owned saved workflow |
| `GET` | `/scheduled-runs/<id>/` | Retrieve one scheduled run |
| `PUT` | `/scheduled-runs/<id>/` | Update schedule fields |
| `DELETE` | `/scheduled-runs/<id>/` | Delete a scheduled run |
| `POST` | `/scheduled-runs/<id>/run-now/` | Queue one immediate execution |
| `GET` | `/scheduled-runs/<id>/executions/` | List execution history |

### Env changes
- New optional var: `CELERY_BROKER_URL`. Defaults to `REDIS_URL`, then `redis://localhost:6379/0` for non-Docker local Celery when both broker env vars are blank.
- `REDIS_URL` is now also used as the default Celery broker URL when `CELERY_BROKER_URL` is unset.

### Runtime notes
- Scheduled execution requires Redis, Celery worker, and Celery Beat. The web container alone only exposes the API.
- Local Docker Compose now starts `redis`, `worker`, and `beat` services alongside `backend`.
- The backend web container runs migrations on startup; worker and beat set `RUN_MIGRATIONS=false` to avoid concurrent migration attempts.

### Manual follow-up
- Run `python manage.py migrate` before using scheduled runs.
- In production/staging, configure a managed Redis URL through `CELERY_BROKER_URL` or `REDIS_URL`.

---

## 2026-06-16 — Saved workflows

### Summary
Added saved workflows: users can store a validated `Plan` JSON (steps, params, tool names) and replay it later via a single API call without re-planning. Two creation paths: generate via LLM then save, or build manually using the tool-schemas endpoint. Run endpoint calls `execute()` directly — deterministic, cheap (no LLM call), and inspectable.

### Files changed
- `agent/models.py` — new `SavedWorkflow` model (`user`, `name`, `description`, `plan` JSONField, optional `project` FK, timestamps)
- `agent/migrations/0004_savedworkflow.py` — generated migration
- `agent/admin.py` — `SavedWorkflowAdmin` registered
- `agent/workflow_views.py` — new; CRUD (`workflow_list_view`, `workflow_detail_view`) + run (`workflow_run_view`) + tool schemas (`workflow_tools_view`)
- `backend/urls.py` — four new routes under `/agent/workflows/`
- `agent/tests/test_workflows.py` — 20 tests covering CRUD, isolation, validation, run, tools endpoint

### Endpoints added
| Method | Path | Description |
|---|---|---|
| `GET` | `/agent/workflows/` | List saved workflows |
| `POST` | `/agent/workflows/` | Create a workflow |
| `GET` | `/agent/workflows/tools/` | All tool schemas (for frontend builder) |
| `GET` | `/agent/workflows/<id>/` | Retrieve one workflow |
| `PUT` | `/agent/workflows/<id>/` | Update name/description/plan |
| `DELETE` | `/agent/workflows/<id>/` | Delete |
| `POST` | `/agent/workflows/<id>/run/` | Execute stored plan directly |

### Manual follow-up
- Run `python manage.py migrate` to create the `saved_workflows` table.

---

## 2026-06-16 — Persistent memory / user profile

### Summary
Added per-user persistent memory: a `UserMemory` model that stores arbitrary key/value facts (name, location, preferences, etc.) that survive across conversations. Memories are injected into every planner system prompt so the planner can personalise responses without re-asking for context. Two new tools (`memory.save`, `memory.delete`) let the planner update memories during a session. REST CRUD endpoints expose the store to frontend UIs.

### Files changed
- `agent/models.py` — new `UserMemory` model (`user`, `key`, `value`, `source`, timestamps; `unique_together = ('user', 'key')`)
- `agent/migrations/0003_usermemory.py` — generated migration
- `agent/admin.py` — `UserMemoryAdmin` registered
- `agent/views.py` — `_load_user_memories()`, `memories` param on `run_prompt()`, `memory_list_view`, `memory_detail_view`
- `backend/urls.py` — `/agent/memory/` and `/agent/memory/<id>/` routes
- `planner/planner.py` — `{memories}` placeholder in system prompt; rule 13 about memory usage; `_build_system()` + `plan()` + `revise_plan()` updated; memories hashed into `_plan_cache_key()`
- `orchestrator/tools/memory/__init__.py` — new package
- `orchestrator/tools/memory/api.py` — `memory.save` and `memory.delete` tools (`requires_user_id=True`)
- `orchestrator/tools/memory/tests.py` — tool registration + call routing tests
- `agent/tests/test_memory.py` — view tests (list, upsert, update, delete, auth, ownership)
- `docs/FEATURES.md` — Persistent Memory section added

### Behavior changes
- Every planner call now receives the user's memory entries as `- key: value` bullet points in the system prompt.
- The planner system prompt now includes rule 13: treat memories as ground truth; use `memory.save` / `memory.delete` when the user asks to remember or forget something.
- Plan cache key now includes a hash of the user's memories so different users (or the same user after updating memories) get distinct cached plans.

### Manual follow-up
- Run `python manage.py migrate` to create the `user_memories` table.

---

## 2026-06-15 — Web search tool (Tavily)

### Summary
Added `web.search` as a built-in tool backed by the Tavily Search API. The tool is auto-discovered by `orchestrator/tools/__init__.py` and always available to the planner (no plugin gate, no OAuth). Returns up to 10 ranked results with title, URL, content snippet, relevance score, and an optional AI-synthesized direct answer.

### Files changed
- `orchestrator/tools/web/__init__.py` — new; triggers registration
- `orchestrator/tools/web/api.py` — new; `web_search()` function + `register()`
- `orchestrator/tools/web/tests.py` — new; tests covering results, clamping, include_answer, missing key, and registry

### Env changes
- New required var: `TAVILY_API_KEY` — get an API key at https://tavily.com

### Behavior changes
- `web.search` now appears in all planner tool schemas (no plugin required). Searches that need current information will naturally route here.

### Secrets / security actions
- None. `TAVILY_API_KEY` is a server-side secret; never sent to the client.

### Manual follow-up
- Add `TAVILY_API_KEY` to your production environment.
- `requests` is already in requirements; no new dependency.

---

## 2026-06-03 — Frontend image runner compose file

### Summary
Added an image-only Compose workflow so frontend developers can run the backend locally from a prebuilt GHCR image without cloning backend source code.

### Files changed
- `compose.image.yaml` — new image runner using `AIVA_BACKEND_IMAGE`, `.env`, port `8000`, and `restart: unless-stopped`
- `.env.example` — added placeholder env contract, including optional image-runner variables
- `docs/SETUP.md` — updated frontend developer instructions to use `docker compose -f compose.image.yaml pull/up/down`

### Behavior changes
- No backend runtime behavior changed.
- Frontend developers can now use only `compose.image.yaml` plus `.env` to pull and run the backend image.

### Env changes
- Optional local-runner variables:
  - `AIVA_BACKEND_IMAGE`
  - `AIVA_BACKEND_PORT`

### Manual follow-up
- Publish the backend image to GHCR under the tag given to frontend developers.
- If the image is private, give frontend developers GHCR access and a GitHub token for `docker login ghcr.io`.

## 2026-05-15 — Google Drive OAuth plugin (metadata-only v1)

### Summary
Added a new connectable `google_drive` plugin and a new `drive.*` tool namespace for read-only Drive metadata discovery. Users can now complete a separate Google Drive OAuth flow, enable `google_drive` in `project.plugins`, and let the planner use Drive tools to list files, search files by name, and inspect file metadata. This version is intentionally metadata-only: no content download, export, create, update, move, or delete actions were added.

### Files changed
- `plugins/plugins/registry.py` — added `google_drive` registry entry with `drive.metadata.readonly` scope and `/plugins/oauth/callback/google_drive/`
- `plugins/services/credentials.py` — added Drive account labeling via Drive About API `user.emailAddress`
- `orchestrator/tools/drive/__init__.py`, `orchestrator/tools/drive/api.py` — new Drive tool package with `drive.list_files`, `drive.search_files`, `drive.get_file_metadata`
- `orchestrator/tools/drive/tests.py` — new tool tests
- `plugins/tests/test_plugins.py` — OAuth registry/connect/callback/refresh coverage for `google_drive`
- `agent/tests/test_views.py` — plugin-gating coverage for Drive tools
- `README.md`, `plugins/README.md`, `docs/FEATURES.md`, `docs/ENDPOINTS.md`, `docs/SETUP.md` — documentation updates

### Behavior changes
- `/plugins/registry/` now includes `google_drive`
- `POST /plugins/oauth/connect/` accepts `{"plugin": "google_drive"}`
- `GET /plugins/oauth/callback/google_drive/` participates in the generic Google Drive callback flow. Current behavior stores a pending OAuth result and requires `POST /plugins/oauth/finalize/` before writing a `PluginCredentials` row with `plugin="google_drive"`.
- Planner-visible tools now include:
  - `drive.list_files`
  - `drive.search_files`
  - `drive.get_file_metadata`
- Drive tools only appear when `project.plugins["google_drive"]` is enabled

### Env changes
- None. The plugin reuses `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.

### Secrets / security actions
- None in the original Google Drive change. The generic connect/callback flow has since been hardened with server-side one-time state and authenticated OAuth finalization.

### Manual follow-up
- Enable the Google Drive API in the Google Cloud project behind `GOOGLE_CLIENT_ID`.
- Register `PUBLIC_BACKEND_URL + /plugins/oauth/callback/google_drive/` as an authorized redirect URI.

## 2026-05-11 — Redis cache backend

### Summary
Added `redis[hiredis]` to requirements and wired Django's built-in `RedisCache` backend into `settings.py`. When `REDIS_URL` is set, all cache operations (plan caching, Gmail pagination cursors, stream rate limiting, modify count) are shared across Gunicorn workers. When unset, Django falls back to `LocMemCache` so local dev and the test suite work without a running Redis instance.

### Files changed
- `requirements.txt` — `redis==7.4.0`, `hiredis==3.3.1`
- `backend/settings.py` — `CACHES` block conditioned on `REDIS_URL` env var
- `backend/tests.py` — new; 3 tests verifying LocMemCache fallback and RedisCache selection

### Behavior changes
- In production with `REDIS_URL` set: cache is shared across workers. Without it: no change.

### Env changes
- New optional var: `REDIS_URL` (e.g. `redis://localhost:6379/0` or `rediss://...` for TLS). Leave empty for LocMemCache.

### Secrets / security actions
- None.

### Manual follow-up
- Set `REDIS_URL` in your production environment (Railway, Render, Fly.io, etc.).

---

## 2026-05-11 — P2/P3: modify cap, audit filtering, PlannerUsage retention, capabilities setting

### Summary
Four quality-of-life improvements to `agent/`:

1. **P2 — Modify cap**: `run_prompt` now limits plan revisions to `AGENT_MAX_MODIFY_REVISIONS` (default 5). When the cap is hit the pending plan is cleared and the user is told to start fresh. The modify count is stored in Django cache (`pending_modify_count:<uid>:<pid>`) and reset on confirm, cancel, or new plan. `pending_plan.py` gains `get_modify_count`, `increment_modify_count`, `reset_modify_count` helpers.

2. **P3 — Audit log filtering**: `GET /agent/actions/` now accepts optional `?tool=`, `?status=`, and `?since=<ISO 8601 datetime>` query params. Invalid `?since=` returns 400.

3. **P3 — PlannerUsage retention**: New management command `purge_planner_usage` deletes rows older than `PLANNER_USAGE_RETENTION_DAYS` (default 90 days). Supports `--days` override and `--dry-run`.

4. **P3 — Capabilities phrases configurable**: `_is_capabilities_query` now reads from `settings.CAPABILITIES_PHRASES` (list of strings) if set, falling back to the hardcoded default set. No redeploy needed to add new trigger phrases.

### Files changed
- `agent/pending_plan.py` — `get_modify_count`, `increment_modify_count`, `reset_modify_count` (cache-backed)
- `agent/views.py` — modify cap in `run_prompt`; `?tool/status/since` filters in `actions_view`; `_capabilities_phrases()` reads from settings
- `agent/management/__init__.py`, `agent/management/commands/__init__.py`, `agent/management/commands/purge_planner_usage.py` — new management command
- `agent/tests/test_views.py` — 7 new tests (5 audit filtering, 2 modify cap)

### Behavior changes
- Repeated modify requests beyond the cap get a "start fresh" response instead of burning more LLM calls.
- `GET /agent/actions/` is now filterable by tool, status, and date.
- `manage.py purge_planner_usage` is available for scheduled cleanup.

### Env changes
- Optional: `AGENT_MAX_MODIFY_REVISIONS` (int, default 5), `PLANNER_USAGE_RETENTION_DAYS` (int, default 90), `CAPABILITIES_PHRASES` (list of strings).

### Secrets / security actions
- None.

### Manual follow-up
- Wire `purge_planner_usage` into Celery Beat or a cron job (e.g. daily).

---

## 2026-05-11 — P2: weather.get_weather_forecast switched to free OWM endpoint

### Summary
`get_weather_forecast` was calling `/data/2.5/forecast/daily`, which requires a paid OpenWeatherMap subscription — free API keys receive a 401. Switched to `/data/2.5/forecast` (free tier, 3-hour intervals up to 5 days). The response is collapsed into one day-level summary per calendar date (temp_min, temp_max, most-common description), preserving the same user-facing shape. Max forecast window is now 5 days instead of the previously claimed 16.

### Files changed
- `orchestrator/tools/weather/api.py` — `get_weather_forecast` switched to `/forecast`; added day-grouping logic; updated `ToolDef` description

### Behavior changes
- Weather forecast now works on free OWM API keys.
- Response format changes: `{"city": "...", "forecast": [{"date", "temp_min", "temp_max", "description"}, ...]}` instead of raw OWM JSON.

### Env changes
- None.

### Secrets / security actions
- None.

### Manual follow-up
- None.

---

## 2026-05-11 — P2/P3: processing_llm timeout + max_tokens; contacts.delete

### Summary
Three small but impactful gaps closed:

1. **P2 — `processing_llm` timeout**: `call_processing_llm` now passes `timeout=_timeout()` (reads `PROCESSING_LLM_TIMEOUT`, default 60 s) to the OpenAI call. A stalled response no longer blocks indefinitely; matches the pattern already used by the planner.

2. **P3 — `processing_llm` max_tokens**: Also passes `max_tokens=_max_tokens()` (reads `PROCESSING_LLM_MAX_TOKENS`, default 1024) to cap unexpectedly long LLM outputs on large inputs.

3. **P3 — `contacts.delete`**: Added `_delete_contact()` DB helper, `contacts_delete()` tool function, and `contacts.delete` `ToolDef` registration (`requires_confirmation=True`). Users can now remove contacts via the agent.

### Files changed
- `orchestrator/tools/processing_llm/tool.py` — `_timeout()`, `_max_tokens()` helpers; `timeout` and `max_tokens` kwargs on `create()`
- `orchestrator/tools/contacts/api.py` — `_delete_contact()` sync helper; `contacts_delete()` tool function; `contacts.delete` registration
- `orchestrator/tools/processing_llm/tests.py` — new; 2 tests verifying timeout/max_tokens are forwarded and defaults work
- `orchestrator/tools/contacts/tests_delete.py` — new; 7 tests (TransactionTestCase) covering delete success, wrong-user isolation, and nonexistent-contact error

### Behavior changes
- Long or stalled `processing_llm` calls now time out after 60 s (configurable).
- `processing_llm` responses capped at 1024 tokens by default (configurable).
- `contacts.delete` is now a valid plan step.

### Env changes
- Optional: `PROCESSING_LLM_TIMEOUT` (int seconds, default 60), `PROCESSING_LLM_MAX_TOKENS` (int, default 1024).

### Secrets / security actions
- None.

### Manual follow-up
- None.

---

## 2026-05-10 — P3: Gmail action tools (trash, mark read/unread, labels, draft)

### Summary
Added six inbox-management tools to `orchestrator/tools/gmail/api.py` via new methods on `_GmailAPI`:

- `gmail.trash_email` — `service.messages().trash()`, `requires_confirmation=True`
- `gmail.mark_read` — removes the `UNREAD` label via `messages().modify()`
- `gmail.mark_unread` — adds the `UNREAD` label via `messages().modify()`
- `gmail.add_label` — resolves label name → ID via `labels().list()`, then `modify(addLabelIds)`
- `gmail.remove_label` — same resolution, then `modify(removeLabelIds)`
- `gmail.create_draft` — `drafts().create()`, no confirmation needed

### Files changed
- `orchestrator/tools/gmail/api.py` — 6 new methods on `_GmailAPI`; 6 new `ToolDef` registrations; `_resolve_label_id()` helper
- `orchestrator/tools/gmail/tests_actions.py` — new; 13 tests across 5 test classes

### Behavior changes
- Users can now instruct the agent to trash, label, and draft emails.

### Env changes
- None.

### Secrets / security actions
- None.

### Manual follow-up
- None.

---

## 2026-05-10 — P1/P2/P3: Google Calendar OAuth fix, delete_event, list_calendars

### Summary
Three related changes to `orchestrator/tools/calendar/api.py`:

1. **P1 — OAuth token refresh fix**: `_build_service` now passes `client_id`, `client_secret`, and `scopes` to `google.oauth2.credentials.Credentials`. Without these fields the Google library cannot refresh an expired access token, causing silent 401 failures. Gmail's `_build_service` already passed all five fields correctly; Calendar now matches.

2. **P2 — `calendar.delete_event` implemented**: The 2026-05-03 changelog listed this tool as delivered but it was never written. Added `calendar_delete_event(token_data, event_id, calendar_id)` using `service.events().delete()`, registered with `requires_confirmation=True`.

3. **P3 — `calendar.list_calendars` added**: Users with multiple calendars (work, personal, shared) had no way to discover non-primary calendar IDs. Added `calendar_list_calendars(token_data)` using `service.calendarList().list()`, returns id, summary, access_role, and primary flag. No confirmation required.

### Files changed
- `orchestrator/tools/calendar/api.py` — `_build_service` fix; `calendar_delete_event` function + `ToolDef` registration; `calendar_list_calendars` function + `ToolDef` registration
- `orchestrator/tools/calendar/tests.py` — new; 11 tests across `BuildServiceTests`, `CalendarDeleteEventTests`, `CalendarListCalendarsTests`, `CalendarToolRegistrationTests`

### Behavior changes
- Calendar access tokens that expire will now refresh automatically rather than failing with 401.
- `calendar.delete_event` is now a valid plan step; plans referencing it will no longer raise `UnknownToolError`.
- `calendar.list_calendars` is available to the planner for multi-calendar workflows.

### Env changes
- None (already required `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` for Gmail).

### Secrets / security actions
- None.

### Manual follow-up
- None.

---

## 2026-05-08 — P3: Audit log for confirmed agent actions

### Summary
`AgentAction` was already modelled and the orchestrator already called `_record_action`, but the table wasn't accessible to clients or admins. Added Django admin registration, a `GET /agent/actions/` read endpoint (with `?limit=N`, default 50, capped 200), and 11 new tests covering the endpoint and end-to-end record creation.

### Files changed
- `agent/admin.py` — new file; registers `AgentAction` and `PlannerUsage` in Django admin with readonly fields, filters, and search
- `agent/views.py` — new `actions_view` (GET, authenticated); returns `{actions: [{id, tool, params_summary, status, timestamp}]}`
- `backend/urls.py` — `path('agent/actions/', actions_view, name='agent-actions')`
- `agent/tests/test_views.py` — 8 new `AgentActionsViewTests` (auth, empty list, own-records-only, field shape, limit, capped limit, invalid limit, ordering)
- `orchestrator/tests/test_orchestrator.py` — 3 new `AgentActionAuditTests` (confirmed success creates record, confirmed failure creates failed record, non-confirmation step creates no record); uses `TransactionTestCase` so `sync_to_async` thread sees committed rows

### Behavior changes
- `GET /agent/actions/` now returns the current user's recent confirmed-action audit records, newest first.

### Env changes
- None.

### Secrets / security actions
- None.

### Manual follow-up
- None (table already existed via `0001_initial`).

---

## 2026-05-08 — P3: Expanded `/agent/` test coverage (+18 tests)

### Summary
Added 18 new tests across `agent/tests/test_views.py` and `orchestrator/tests/test_orchestrator.py`, covering previously untested paths.

### Files changed
- `agent/tests/test_views.py` — added imports; new `FormatCompletedStepsTests` (4), `AgentViewErrorTests` (5: PluginNotConnectedError→422, ToolExecutionError→500 with friendly message, completed_steps included/omitted, UnknownToolError→400), `AgentViewCapabilitiesTests` (2: planner skipped, tool groups listed); extended `AgentStreamViewTests` with 2 error-event tests (PluginNotConnectedError and ToolExecutionError with completed_steps)
- `orchestrator/tests/test_orchestrator.py` — new `ExecuteCompletedStepsTests` (5: empty on first-step failure, prior steps accumulated, irreversible flag set, dict keys present, multi-step accumulation)

### Behavior changes
- No production code changes.

### Env changes
- None.

### Secrets / security actions
- None.

### Manual follow-up
- None.

---

## 2026-05-08 — P3: Multi-step plan partial-failure reporting

### Summary
When a multi-step plan fails mid-execution, the error response and SSE error event now include the list of completed steps (with tool name and irreversibility flag). The LLM-generated friendly error message is explicitly instructed to mention what was already accomplished and warn about any irreversible actions (e.g. an email that was sent before the failure).

### Files changed
- `orchestrator/exceptions.py` — `ToolExecutionError.completed_steps` changed from `list[str]` (step IDs) to `list[dict]` with `{step_id, tool, requires_confirmation}`
- `orchestrator/orchestrator.py` — `completed` accumulator changed to `list[dict]`; each append now includes `step_id`, `tool`, and `requires_confirmation` from the tool definition
- `agent/views.py` — added `_format_completed_steps()` helper; both `agent_view` and `agent_stream_view` `ToolExecutionError` handlers now pass a formatted completed-steps string in `inputs` and use an updated `task` prompt that instructs the LLM to mention prior results and flag irreversible ones

### Behavior changes
- `error.completed_steps` in `tool_execution_failed` responses is now a list of `{step_id, tool, requires_confirmation}` dicts (was a list of step-ID strings).
- LLM-generated error messages now describe what ran before the failure and warn users about irreversible actions.

### Env changes
- None.

### Secrets / security actions
- None.

### Manual follow-up
- Clients consuming `error.completed_steps` should update from string-array to object-array format.

---

## 2026-05-07 — #25: Multi-account plugin support

### Summary
Users can now connect multiple accounts for the same plugin (e.g. two Gmail addresses). The planner learns which accounts exist, sets `account_id` on each plan step that needs a specific account, and the orchestrator loads credentials for that exact row.

### Files changed
- `planner/schemas.py` — `PlanStep` gains `account_id: Optional[str] = None`
- `plugins/services/credentials.py` — `get_active_credential(account_id=None)` filters to a specific row when provided
- `orchestrator/credentials.py` — `load_credentials(account_id=None)` threads through; new `get_connected_accounts()` returns `{plugin, account_id}` per active row
- `orchestrator/orchestrator.py` — passes `step.account_id` to `load_credentials`
- `planner/planner.py` — `plan()` / `revise_plan()` accept `connected_accounts`; `_build_system` renders per-plugin account lists; rule 4 instructs LLM to set `account_id` when multiple accounts exist; plan cache key hashes sorted `(plugin, account_id)` tuples
- `agent/views.py` — `run_prompt` calls `get_connected_accounts` (one DB query), derives `connected_plugins` from it, passes `connected_accounts` to planner
- `plugins/tests/test_plugins.py` — 4 new `GetActiveCredentialMultiAccountTests`
- `planner/tests/test_planner.py` — cache-key tests updated to `{plugin, account_id}` dict format; added `test_different_accounts_produce_different_key`

### Behavior changes
- `get_active_credential` now accepts `account_id` and filters to that row; without it, returns most-recently-updated (unchanged behavior).
- The planner system prompt now shows accounts per plugin (e.g. `gmail: a@gmail.com, b@gmail.com; google_calendar`) and instructs the LLM to set `account_id` on steps requiring disambiguation.
- Plan cache keys are now invalidated when the account set changes (previously only plugin names were hashed).
- Single-account plugins with `account_id=None` behave identically to before.

### Env changes
- None.

### Secrets / security actions
- None.

### Manual follow-up
- None (no migration required; `Credentials.account_id` column already existed).

---

## 2026-05-07 — #9/#19: SSE streaming endpoint with per-step progress events

### Summary
Added `POST /agent/stream/` which streams SSE events as each plan step completes, so clients can show a live progress indicator without polling. Also added `on_step` callback to `execute()` and wired it through `run_prompt`.

### Files changed
- `agent/views.py` — `_sse()` helper, `_auth_stream()`, `agent_stream_view` (async SSE view); `run_prompt` gains `on_step=None` param forwarded to both `execute()` call sites
- `backend/urls.py` — added `path('agent/stream/', agent_stream_view)`
- `orchestrator/orchestrator.py` — `execute()` accepts `on_step` async callback, called after each successful step
- `agent/tests/test_views.py` — 6 stream view tests (auth, step events, error propagation)
- `orchestrator/tests/test_orchestrator.py` — 4 `on_step` callback tests

### Behavior changes
- `POST /agent/stream/` accepts the same body as `POST /agent/` and returns `text/event-stream`.
- Events: `status {"message": "Planning..."}` → zero or more `step {"step_id", "tool", "index", "total"}` → `done {"response", "dry_run"}` or `error {"code", "message"}`.
- Skipped dry-run steps do not fire a `step` event.
- All asyncio objects are created inside the generator so they bind to whichever event loop iterates it (ASGI in prod, `asyncio.run` in tests).

### Env changes
- None.

### Secrets / security actions
- None.

### Manual follow-up
- No migration required.
- Clients connecting to `/agent/stream/` must send the `Authorization: Bearer <token>` header (same as `/agent/`).

---

## 2026-05-07 — #26: Plan caching for history-free requests

### Summary
Added SHA-256-keyed Django cache layer in the planner so identical history-free prompts skip the LLM call and return the cached plan. Cross-test pollution bug fixed by `@override_settings(PLAN_CACHE_TTL=0)`.

### Files changed
- `planner/planner.py` — `_plan_cache_key()`, `_cache_get()`, `_cache_set()`; `plan()` checks/sets cache when `history == []` and `PLAN_CACHE_TTL > 0`
- `planner/tests/test_planner.py` — `PlanCacheKeyTests`, `PlanCachingTests`; `PlannerLLMTests` base changed to `SimpleTestCase` with `@override_settings(PLAN_CACHE_TTL=0)`

### Behavior changes
- History-free plans are cached in Django's default cache backend under `aiva:plan:<sha256>`.
- Cache TTL defaults to 3600 s; set `PLAN_CACHE_TTL=0` to disable.
- Plans with non-empty history are never cached.
- Cache key includes model, prompt, sorted `(plugin, account_id)` tuples, and a hash of tool schemas.

### Env changes
- `PLAN_CACHE_TTL` (optional, default `3600`): plan cache TTL in seconds; `0` disables caching.

### Secrets / security actions
- None.

### Manual follow-up
- Configure a real cache backend (Redis) in production via `CACHES` Django setting for cross-process sharing; default `LocMemCache` is per-process only.

---

## 2026-05-05 — P2: Validate plan tools before showing summary; mark rate limiting done

### Summary
Added `_validate_plan_tools(plan)` in `agent/views.py` which iterates every step and calls `get_tool(step.tool)`, raising `UnknownToolError` immediately if any step references an unregistered tool. Called explicitly after `make_plan` (Branch B) and after `revise_plan` (modify branch). Previously, fresh plans relied on `_needs_confirmation` as a side-effect validator, and revised plans were never validated — an unknown tool in a revised plan would only fail at execution time, after the summary had already been shown to the user. Rate limiting (`AgentThrottle` / `@throttle_classes`) was already implemented in a prior session; TODO item marked done.

### Files changed
- `agent/views.py` — added `_validate_plan_tools`, wired into fresh-plan and revise-plan branches; removed side-effect validation comment from `_needs_confirmation`
- `agent/tests/test_views.py` — added `test_validate_plan_tools_passes_for_known_tool`, `test_validate_plan_tools_raises_for_unknown_tool`, `test_modify_with_unknown_tool_returns_400`
- `docs/TODO.md`

### Behavior changes
- A revised plan referencing an unknown tool now returns 400 immediately, before the summary is shown or the plan is stored. Previously it would be stored and only fail at execution time when the user confirmed.

### Env changes
- None.

---

## 2026-05-05 — P2: Encrypt OAuth tokens at rest

### Summary
`access_token` and `refresh_token` on `plugins.Credentials` were stored as plain `TextField`. A DB dump or SQL injection would expose live OAuth credentials for every connected user. Added `EncryptedTextField` (Fernet symmetric encryption from `cryptography`, already a dependency) that transparently encrypts on write and decrypts on read. Supports multi-key rotation via `CREDENTIAL_ENCRYPTION_KEYS` (list) with `MultiFernet`. Added a data migration that encrypts any existing plaintext rows before the `AlterField` that changes column behaviour, avoiding chicken-and-egg decrypt failures.

### Files changed
- `plugins/fields.py` — new `EncryptedTextField` with `_get_fernet()`, `from_db_value`, `get_prep_value`
- `plugins/models.py` — `access_token` and `refresh_token` changed from `TextField` to `EncryptedTextField`
- `plugins/migrations/0002_encrypt_credential_tokens.py` — `RunPython` encrypts existing rows, then `AlterField` changes both token fields
- `backend/settings.py` — added `CREDENTIAL_ENCRYPTION_KEY = env("CREDENTIAL_ENCRYPTION_KEY", default="")`
- `plugins/tests/test_plugins.py` — added `CREDENTIAL_ENCRYPTION_KEY` to `@override_settings`, added `test_tokens_are_encrypted_at_rest` raw-cursor assertion
- `docs/SETUP.md` — added `CREDENTIAL_ENCRYPTION_KEY` to env contract with `Fernet.generate_key()` generation command
- `README.md` — added `CREDENTIAL_ENCRYPTION_KEY` to core env list
- `docs/TODO.md`

### Behavior changes
- OAuth tokens are now Fernet-encrypted in `PluginCredentials`. The change is transparent to callers — ORM reads/writes work identically.
- Historical note: this change originally allowed raw-value fallback on reads during migration. Current runtime behavior now fails closed unless `CREDENTIAL_ENCRYPTION_ALLOW_PLAINTEXT_FALLBACK=true` is explicitly set for a controlled migration window.

### Env changes
- `CREDENTIAL_ENCRYPTION_KEY` (required): a URL-safe base64-encoded 32-byte Fernet key. Generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
- `CREDENTIAL_ENCRYPTION_KEYS` (optional): comma-separated list of keys for rotation; `MultiFernet` tries them in order, so the first key is used for new encryptions.

### Migration notes
- `plugins/migrations/0002_encrypt_credential_tokens.py` runs `RunPython` first to encrypt existing rows, then `AlterField`. If `CREDENTIAL_ENCRYPTION_KEY` is not configured at migration time, the `RunPython` step is a no-op (safe for fresh installs with no rows; unsafe for production with existing rows — set the key before migrating).

---

## 2026-05-04 — P2: Tighten `/agent/` request validation and project scoping

### Summary
`/agent/` was parsing the request body with `json.loads(request.body)` and accepting any `project_id` value without verifying it referred to a real project owned by the user. An invalid or foreign `project_id` was silently ignored (falling back to no plugin restriction). Replaced manual JSON parsing with `AgentRequestSerializer`, moved project lookup to the view layer with `get_object_or_404`, and simplified `_get_enabled_plugins` to take an already-fetched `Projects` instance. Enabled plugins are now computed in the view and passed into `run_prompt` rather than re-queried inside it.

### Files changed
- `agent/views.py` — added `AgentRequestSerializer`, tightened `_get_enabled_plugins(project)`, restructured `agent_view` validation before execution try/except, updated `run_prompt` signature
- `agent/tests/test_views.py` — updated `PluginFilterHelperTests` for new signature, added `AgentViewProjectScopingTests` (4 tests: 400 on non-integer project_id, 404 on unknown project, 404 on other user's project, 200 on valid project)
- `docs/TODO.md`

### Behavior changes
- `POST /agent/` with a non-integer `project_id` now returns 400 (was silently ignored)
- `POST /agent/` with an unknown or foreign `project_id` now returns 404 (was silently ignored, falling back to no plugin restriction)

### Env changes
- None.

---

## 2026-05-04 — P2: Remove dead insecure Supabase auth middleware

Note: the later 2026-06-10 entry restored `SUPABASE_ANON_KEY` as an optional setting for developer login-helper compatibility. It remains optional for Django runtime auth.

### Summary
Deleted `authentication/middleware.py`, which contained a Django middleware class (`SupabaseAuthMiddleware`) that decoded JWTs with `verify_signature: False` — cryptographically insecure and never used in production. The live auth path is `authentication/authentication.py` (`SupabaseAuthentication` DRF class), which properly verifies tokens using `SUPABASE_JWT_SECRET`. The anon key is only needed to call Supabase's auth REST API directly (e.g., for manual token requests during testing), not for backend API authentication.

### Files changed
- `authentication/middleware.py` — deleted
- `backend/settings.py` — removed the commented-out middleware reference and stopped requiring `SUPABASE_ANON_KEY` for the active auth path
- `docs/SETUP.md` — removed anon key from `.env` example and Supabase locations table; added note clarifying it's only needed for direct Supabase API calls
- `README.md` — removed `SUPABASE_ANON_KEY` from required env vars list
- `docs/TODO.md`

### Behavior changes
- None — the middleware was already disabled (commented out in `MIDDLEWARE`).

### Env changes
- `SUPABASE_ANON_KEY` is not required for Django backend runtime. It is still needed if you call Supabase's auth endpoint directly for testing.

### Secrets / security actions
- Eliminated insecure dead code path: `verify_signature: False` JWT decoding can no longer be accidentally re-enabled.

---

## 2026-05-04 — P2: Simplify Tasks/SubTasks to plain CRUD; remove execution-state fields

### Summary
Decided that Task/SubTask are user-managed planning objects, not orchestrator execution records. Removed 5 SubTask fields that implied backend-managed execution state (`dependencyRequired`, `confirmationRequired`, `confirmationStatus`, `status`, `result`) — none were ever written by the API or the orchestrator. Added PATCH to `TaskDetailView` so `Task.status` is now user-updatable. Switched serializers from `__all__` to explicit field lists.

### Tasks
- `SubTask` model: removed `dependencyRequired`, `confirmationRequired`, `confirmationStatus`, `status`, `result`.
- `tasks/serializers.py`: switched from `fields = '__all__'` to explicit field lists on both `SubTaskSerializer` and `TaskSerializer`.
- `tasks/views.py`: added `PATCH /tasks/<projectId>/<taskId>/` for partial task updates (title, description, status).
- Migration `0002_remove_subtask_execution_state_fields` drops the 5 columns.
- Added 4 new tests: execution-state fields absent from response, PATCH status, PATCH title.

### Files changed
- `tasks/models.py`
- `tasks/serializers.py`
- `tasks/views.py`
- `tasks/tests/test_tasks.py`
- `tasks/migrations/0002_remove_subtask_execution_state_fields.py`
- `docs/TODO.md`

### Behavior changes
- SubTask API responses no longer include `dependencyRequired`, `confirmationRequired`, `confirmationStatus`, `status`, `result`.
- `PATCH /tasks/<projectId>/<taskId>/` is now a valid endpoint for updating task fields.

### Env changes
- None.

### Secrets / security actions
- None.

### Manual follow-up
- Run `python manage.py migrate` on any deployed instance.

---

## 2026-05-04 — P1: Enforce project plugin selection in agent path

### Summary
`project.plugins` (format: `{"gmail": true, "google_calendar": false}`) now has real effect. `run_prompt()` reads the project's plugin config, filters `tool_schemas` and `connected_plugins` before passing them to the planner, and validates each new/revised plan against the enabled set before execution. Empty dict (default) = no restriction.

### Agent / Planner
- `_get_enabled_plugins(user_id, project_id)` — loads project, returns `frozenset` of enabled plugin IDs or `None` (no restriction).
- `_validate_plan_plugins(plan, enabled_plugins)` — raises `UnknownToolError` if any plan step uses a tool from a disabled plugin; called before every execute or pending-plan save.
- `get_schemas_for_planner(enabled_plugins=...)` — new optional param; filters out tools whose `plugin_id` is not in the enabled set; tools with `plugin_id=None` (processing_llm, weather, contacts) are always included.
- `_capabilities_response()` now iterates the already-filtered `tool_schemas` instead of the full `_REGISTRY`, so capabilities queries respect project restrictions.
- `connected_plugins` list is also filtered to the enabled set before being passed to the planner.
- Moved `from projects.models import Projects` to module-level import in `agent/views.py`.
- Added 12 new unit tests covering `_get_enabled_plugins`, `_validate_plan_plugins`, and `get_schemas_for_planner` filtering.

### Files changed
- `orchestrator/tool_registry.py`
- `agent/views.py`
- `agent/tests/test_views.py`
- `docs/TODO.md`

### Behavior changes
- Projects with a non-empty `plugins` field now restrict the tool set and connected plugins visible to the planner.
- Projects with `plugins: {}` (default) have no restriction — unchanged behavior.
- Capabilities query (`"what can you do?"`) reflects only project-enabled tools.

### Env changes
- None.

### Secrets / security actions
- None.

### Manual follow-up
- None.

---

## 2026-05-04 — P1: Collapse duplicate plugin registries; single canonical source

### Summary
`plugins/plugins/registry.py` is now the single canonical source for all plugin metadata. Added `contact_service` field (e.g. `"Gmail"`) and the derived `CONTACT_SERVICES` frozenset. `contacts/views.py` now validates against the registry instead of reading `plugins.json`. Deleted `plugins.json` and `contacts/plugins.json`.

### Plugins / Contacts
- `PLUGIN_REGISTRY` gains `contact_service: str | None` per entry; `CONTACT_SERVICES` frozenset derived at import time.
- `contacts/views.py`: replaced file I/O + JSON parse with a registry import; removed `os`, `json`, `BASE_DIR`, `AVAILABLE_PLUGINS`.
- `contacts/tests/test_contacts.py`: removed `AVAILABLE_PLUGINS` write from `test_create_valid_contact_connection`; test now relies on the registry directly.
- `plugins.json` (deleted) — was read by `contacts/views.py` for validation.
- `contacts/plugins.json` (deleted) — was orphaned; runtime never read it.

### Files changed
- `plugins/plugins/registry.py`
- `contacts/views.py`
- `contacts/tests/test_contacts.py`
- `plugins.json` (deleted)
- `contacts/plugins.json` (deleted)
- `docs/TODO.md`

### Behavior changes
- `POST /contacts/<id>/connections/` now validates `service` against the registry's `CONTACT_SERVICES` set instead of parsing a JSON file at request time.

### Env changes
- None.

### Secrets / security actions
- None.

### Manual follow-up
- None.

---

## 2026-05-04 — P1: Unify context stores; append-only saves with activeContextFrom pruning

### Summary
Fixed the split between the agent's LLM context buffer and the `/project-context/` UI transcript. Both already wrote to the same `ProjectContext` table, but the agent used a destructive delete-then-recreate save that wiped frontend-written rows on every message. Replaced with append-only inserts using `select_for_update()` + `MAX(sequence)+1` (matching `context/views.py`'s pattern). Pruning now advances `Projects.activeContextFrom` instead of deleting rows, so the DB retains the full transcript while the LLM context window slides forward. Reset endpoint now also resets `activeContextFrom = 0`.

### Agent / Conversation Context
- `DbContextStore.save()` is now append-only: inserts only messages with no DB sequence yet; existing rows are never touched.
- `ChatContext` tracks `_sequences` (parallel list, `None` = unsaved) and `_active_from` (pending `activeContextFrom` value).
- `_prune()` advances `_active_from` past pruned rows instead of deleting them; `load()` filters `sequence >= activeContextFrom` for the LLM window.
- `SELECT FOR UPDATE` on `MAX(sequence)` prevents sequence collisions with concurrent frontend writes via `context/views.py`.
- `DELETE /agent/reset/<project_id>/` now also sets `activeContextFrom = 0` so post-reset messages are visible on the next load.
- Removed `test_save_overwrites_previous_messages` and `test_save_empty_messages_clears_db` (they tested the old destructive behavior); replaced with 8 new tests covering append, prune cursor, DB row retention, and reset round-trip.

### Files changed
- `agent/chat_context.py`
- `agent/views.py`
- `agent/tests/test_chat_context.py`
- `docs/FEATURES.md`
- `docs/TODO.md`

### Behavior changes
- Agent writes no longer delete frontend-written `ProjectContext` rows.
- `activeContextFrom` now has real effect: it slides forward on prune and resets on conversation reset.
- Old rows are retained in DB after pruning (visible via `/project-context/` as full transcript history).

### Env changes
- None.

### Secrets / security actions
- None.

### Manual follow-up
- None.

---

## 2026-05-04 — File cleanup: remove orphaned dev scripts and redundant files

### Summary
Removed `backend/test_login.py` (one-off Supabase login script superseded by the curl instructions in `docs/SETUP.md`) and `contacts/plugins.json` (orphaned file — live runtime reads from the root `plugins.json` only). Updated `send_prompt.py` comment to reference `docs/SETUP.md` instead of the deleted script.

### Files changed
- `backend/test_login.py` (deleted)
- `contacts/plugins.json` (deleted)
- `send_prompt.py`

### Behavior changes
- None. Both deleted files were unused by the live runtime.

### Env changes
- None.

### Secrets / security actions
- None.

### Manual follow-up
- None.

---

## 2026-05-03 — Typed errors, DB-backed state, Gmail pagination, dry-run, calendar/contacts tools

### Summary
Migrated chat context and pending plan state from flat files to Django models. Introduced a typed exception hierarchy, structured HTTP error responses, Gmail cursor-based pagination, a dry-run/preview mode, a reset endpoint, connected-plugin-aware planning, planner token tracking, and new Calendar and Contacts tool modules. Removed stale compose files.

### Agent (`agent/`)

- `agent/models.py` (new): `ProjectContext` model stores LLM conversation buffer per `(user, project_id)`. `PlannerUsage` model records input/output token counts per planner call.
- `agent/chat_context.py`: rewritten to read/write `ProjectContext` DB rows; context pruning now uses `tiktoken` (`cl100k_base`) instead of character count, with a character heuristic fallback.
- `agent/pending_plan.py`: rewritten to read/write `Projects.pending_plan` JSONField instead of flat files.
- `agent/views.py`:
  - `POST /agent/` accepts `"dry_run": true` — steps with `requires_confirmation=True` are skipped with a placeholder; response includes a dry-run notice and `"dry_run": true`.
  - `DELETE /agent/reset/<project_id>/` (new) — clears `ProjectContext` rows and `pending_plan` for a project ("Start fresh").
  - `ToolExecutionError` handler calls `call_processing_llm` to produce a natural-language explanation; falls back to a generic message if the LLM call fails; HTTP 500 preserved.
- `agent/migrations/0001_initial.py`, `0002_plannerusage.py` (new): DB migrations for `ProjectContext` and `PlannerUsage`.

### Orchestrator (`orchestrator/`)

- `orchestrator/exceptions.py` (new): typed exception hierarchy — `ToolExecutionError`, `UnknownToolError`, `ToolValidationError`. Replaces bare exception strings; `/agent/` responses now include an `error_code` field.
- `orchestrator/orchestrator.py`: `execute()` accepts `dry_run` flag; `_needs_confirmation` flag allows `UnknownToolError` to propagate early at plan-validation time instead of being swallowed.
- `orchestrator/credentials.py`: `get_connected_plugins()` queries active `PluginCredentials` for a user.
- `orchestrator/tool_registry.py`: minor registration updates for new tools.

### Planner (`planner/`)

- `planner/planner.py`:
  - `plan()`, `revise_plan()`, and `detect_intent()` accept `connected_plugins` and `user_id`; planner prompt lists connected plugins and instructs the model not to plan steps for unconnected ones — missing plugin produces a single `processing_llm` step directing the user to Settings → Plugins.
  - Every planner LLM call persists token counts to `PlannerUsage` (no-op if user lookup fails).
  - `_CONFIRM_TOKENS` / `_CANCEL_TOKENS` sets allow direct short-reply matching before LLM classification; raw user message also checked for unambiguous replies.
  - All planner LLM calls respect `PLANNER_TIMEOUT` setting (default 60 s).
  - `max_tokens` for intent classification raised from 5 → 10.

### Gmail Tools (`orchestrator/tools/gmail/`)

- `orchestrator/tools/gmail/api.py`: all fetch methods accept `user_id` and persist a pagination cursor in Django cache (1-hr TTL, keyed by `user_id`). New `gmail.get_next_page` tool fetches the next page of the most recent query; cursor is cleared when no further pages exist.

### Calendar Tools (`orchestrator/tools/calendar/`) — new

- `orchestrator/tools/calendar/api.py`: `calendar.list_events`, `calendar.create_event`, `calendar.update_event`, `calendar.delete_event`. Uses existing `PluginCredentials` Google OAuth flow.

### Contacts Tools (`orchestrator/tools/contacts/`) — new

- `orchestrator/tools/contacts/api.py`: `contacts.list_contacts`, `contacts.search_contacts`, `contacts.create_contact`, `contacts.update_contact`. Uses existing `PluginCredentials` Google OAuth flow.

### Projects / DB (`projects/`)

- `projects/models.py`: added `pending_plan` JSONField to `Projects` model.
- `projects/migrations/0003_projects_pending_plan.py` (new).

### Docker / Infrastructure

- Deleted `compose.dev.yaml` and `compose.image.yaml` (superseded by `docker-compose.yml` + `docker-compose.dev.yml`).
- Removed `mkdir .chat_ctx/.pending_plans` from `Dockerfile` and `entrypoint.sh` (no longer needed).
- `requirements.txt`: added `tiktoken==0.12.0`.

### Env changes

- `CHAT_CTX_DIR` and `PENDING_PLAN_DIR` no longer required (state now in DB; values ignored if present).
- `PLANNER_TIMEOUT` (optional, default `60`): wall-clock timeout in seconds for all planner OpenAI calls.
- No new env vars for Calendar or Contacts tools — same `PluginCredentials` OAuth flow as Gmail.

### Secrets / security actions

- No new secrets. Calendar and Contacts tools use existing Google OAuth credentials.

### Manual follow-up

- Run `python manage.py migrate` to apply the three new migrations (`agent` 0001/0002, `projects` 0003).
- Remove `CHAT_CTX_DIR` and `PENDING_PLAN_DIR` from `.env` (they are ignored).
- Reconnect Google accounts if Calendar or Contacts scopes were not included in existing OAuth grants.
- Restart the backend to load all new tool registrations and exception handlers.

## 2026-04-27 — Added info-level agent execution tracing

### Summary
Added info-level tracing for the `/agent/` request path, orchestrator step execution, and Gmail tool progress so tool-driven agent requests can be diagnosed from normal Docker logs without enabling debug logging.

### Files changed
- `agent/views.py`
- `orchestrator/orchestrator.py`
- `orchestrator/tools/gmail/api.py`
- `backend/settings.py`
- `docs/CHANGELOG.md`

### Behavior changes
- `/agent/` now logs request receipt, planning milestones, confirmation handling, and response completion at info level.
- The orchestrator now logs step start/completion and credential-loading milestones at info level.
- Gmail tool execution now logs list/fetch progress at info level for email retrieval operations.
- Backend logging configuration now emits info-level logs for the `agent`, `orchestrator`, and `planner` logger families to stdout.

### Env changes
- None.

### Secrets / security actions
- No secrets are logged; tracing records IDs, counts, tool names, and prompt length rather than raw tokens.

### Manual follow-up
- Restart the backend so the logging configuration and new tracing code are loaded.
- Re-run a tool-driven `/agent/` prompt and inspect Docker logs to see where execution stalls.

## 2026-04-26 — Agent project ID normalization fix

### Summary
Fixed the `/agent/` request path so numeric `project_id` values from JSON requests are normalized to strings before the backend uses them for file-backed chat context and pending-plan storage.

### Files changed
- `agent/views.py`
- `docs/CHANGELOG.md`

### Behavior changes
- `run_prompt()` now converts non-null `project_id` values to strings before loading or saving chat-context and pending-plan files.
- `POST /agent/` no longer crashes with `TypeError: 'int' object is not iterable` when clients send `project_id` as a JSON number.

### Env changes
- None.

### Secrets / security actions
- None.

### Manual follow-up
- Restart the backend so the updated agent view is loaded.
- Re-test `POST /agent/` with a numeric `project_id` such as `14`.

## 2026-04-26 — Gmail account lookup moved to Gmail profile

### Summary
Changed the Gmail OAuth post-callback account lookup to use the Gmail profile endpoint instead of Google `userinfo`, so the backend can derive the connected Gmail address from the scopes it already requests.

### Files changed
- `plugins/services/credentials.py`
- `ENDPOINTS.md`
- `CHANGELOG.md`

### Behavior changes
- `CredentialService.fetch_account_id()` now calls `https://gmail.googleapis.com/gmail/v1/users/me/profile` for the Gmail plugin.
- The backend now reads `emailAddress` from the Gmail profile response instead of calling Google `userinfo`.
- This aligns the account lookup step with the existing Gmail scopes used by the plugin.

### Env changes
- None.

### Secrets / security actions
- None.

### Manual follow-up
- Restart the backend so the updated credential lookup code is loaded.
- Re-run the Gmail connect flow and confirm the callback no longer logs a `401` from Google `userinfo`.

## 2026-04-24 — Gmail OAuth app-return redirects

### Summary
Updated the Gmail OAuth callback flow so the backend redirects users back into the native app through app deep links. Current OAuth behavior stores credentials only after the authenticated app calls `POST /plugins/oauth/finalize/`.

### Files changed
- `backend/settings.py`
- `plugins/views.py`
- `plugins/tests/test_plugins.py`
- `.env.example`
- `README.md`
- `plugins/README.md`
- `ENDPOINTS.md`
- `SETUP.md`
- `DOCKERIZE_BACKEND.md`
- `CHANGELOG.md`

### Behavior changes
- The Gmail OAuth callback still receives Google’s redirect at `/plugins/oauth/callback/gmail/`, exchanges the code, and stores credentials in `PluginCredentials`.
- After the backend finishes the callback, success now redirects to `aiva://oauth/gmail/success` by default and failure now redirects to `aiva://oauth/gmail/failure` by default.
- The callback no longer falls back to backend-local `/integrations` or `/` when the new env vars are unset.
- Backend tests now assert the actual redirect `Location` values for Gmail OAuth success and failure paths.

### Env changes
Added optional env vars with defaults:
- `PLUGIN_OAUTH_SUCCESS_REDIRECT`
- `PLUGIN_OAUTH_FAILURE_REDIRECT`

### Secrets / security actions
- No new secrets were added.
- `PUBLIC_BACKEND_URL` remains the Google-facing callback base and should not be confused with the app deep-link return targets.

### Manual follow-up
- Add the new env vars to `.env` only if you want to override the default `aiva://oauth/gmail/...` targets.
- Keep the Google OAuth redirect URI configured as `PUBLIC_BACKEND_URL + /plugins/oauth/callback/gmail/`.
- Re-test Gmail connect from the app and confirm the browser is redirected to the `aiva://` success/failure route after the backend callback completes.

## 2026-04-20 — Docker-first backend setup guide

### Summary
Rewrote the backend setup guide around the current Docker configuration so a new machine can bring up the backend through `compose.yaml` while keeping Supabase, Postgres, OpenAI, and Google services external.

### Files changed
- `SETUP.md`
- `CHANGELOG.md`

### Behavior changes
- None. This is documentation-only.

### Env changes
- None.

### Secrets / security actions
- The setup guide now reinforces that secrets are provided through `.env` at runtime and are not baked into the Docker image.

### Manual follow-up
- Follow the Docker-first setup path in `SETUP.md` on new machines.
- Verify `.env` is populated from `.env.example` before running `docker compose up --build`.

## 2026-04-19 — Added backend Docker support files

### Summary
Added the backend-local Docker support files from the Dockerization guide so the service can be built and run as a single container against the existing external Supabase, Postgres, OpenAI, and Google services.

### Files changed
- `Dockerfile`
- `entrypoint.sh`
- `compose.yaml`
- `DOCKERIZE_BACKEND.md`

### Behavior changes
- The backend now has a repo-local `Dockerfile` that installs dependencies, copies the backend source, creates writable runtime-state directories, and starts the ASGI app through `entrypoint.sh`.
- The new `entrypoint.sh` creates the runtime-state directories, runs `python manage.py migrate`, and then launches the configured server command.
- The new `compose.yaml` defines a one-service backend setup with the existing `.env` contract and named volumes for the file-backed state directories.
- The Docker guide now documents the required container-local absolute mount targets for Docker volumes while keeping the backend config itself on repo-relative state paths.

### Env changes
- None.

### Secrets / security actions
- The Docker support files continue to expect secrets at runtime through `.env`; no secrets are baked into the image.

### Manual follow-up
- Build the image and run the container once Docker is available on the target system.
- Verify that `.env` contains the required backend env contract before using `compose.yaml`.
- Re-test `/projects/`, `/agent/`, and Gmail OAuth behavior from the containerized backend.

## 2026-04-17 — Relative path portability cleanup

### Summary
Removed host-specific absolute path literals from the backend docs and examples, switched the example runtime state directories to relative paths, and updated settings so relative runtime directories resolve against the backend project root.

### Files changed
- `backend/settings.py`
- `.env.example`
- `README.md`
- `SETUP.md`
- `ENDPOINTS.md`
- `DOCKERIZE_BACKEND.md`
- `Dockerfile`

### Behavior changes
- `CHAT_CTX_DIR` and `PENDING_PLAN_DIR` now resolve relative to the backend project directory when configured as relative paths.
- Backend docs and markdown links no longer depend on `/Users/...` host-specific paths.
- Example backend runtime-state paths now use repo-relative directories instead of absolute filesystem locations.

### Env changes
Changed examples:
- `CHAT_CTX_DIR=.chat_ctx`
- `PENDING_PLAN_DIR=.pending_plans`

### Secrets / security actions
- None.

### Manual follow-up
- If your local `.env` still uses old absolute runtime-state paths, update it only if you want the new relative-path behavior.
- If you use the repo-local `Dockerfile`, review it before use because it now follows the same relative-path convention as the docs and env examples.

## 2026-04-17 — Backend hardening and runtime cleanup

### Summary
Standardized the backend env contract, removed repo-file secret/runtime dependencies from the live runtime, moved orchestrator credential loading onto `PluginCredentials`, hardened DRF bearer-token auth, and kept agent state file-backed with explicit runtime directories.

### Files changed
- `backend/settings.py`
- `authentication/authentication.py`
- `plugins/views.py`
- `plugins/serializers.py`
- `plugins/services/credentials.py`
- `plugins/plugins/registry.py`
- `orchestrator/credentials.py`
- `orchestrator/orchestrator.py`
- `orchestrator/tools/gmail/api.py`
- `agent/chat_context.py`
- `agent/pending_plan.py`
- `README.md`
- `SETUP.md`
- `plugins/README.md`
- `.env.example`
- `.gitignore`

### Behavior changes
- DRF API auth now verifies Supabase JWT signatures, expiry, and issuer through JWKS derived from `SUPABASE_URL`.
- `REST_FRAMEWORK` no longer includes `SessionAuthentication`; bearer-token DRF auth is the only API auth path.
- Local mirrored user emails are updated when the JWT email claim changes.
- Gmail OAuth callback now uses `/plugins/oauth/callback/gmail/`.
- Gmail credentials are loaded from `PluginCredentials`, not `token.json`.
- Gmail token refresh is owned by `CredentialService`; the Gmail tool no longer refreshes tokens itself.
- Credential GET responses are redacted and no longer expose `access_token` or `refresh_token`.
- Agent chat context and pending plans still use files, but now follow settings-driven paths.

### Env changes
Added or standardized:
- `SECRET_KEY`
- `DEBUG`
- `ALLOWED_HOSTS`
- `CSRF_TRUSTED_ORIGINS`
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_DB_PW`
- `POSTGRES_HOST`
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PORT`
- `POSTGRES_SSLMODE`
- `PUBLIC_BACKEND_URL`
- `OPENAI_KEY`
- `PLANNER_MODEL`
- `PROCESSING_LLM_MODEL`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `CHAT_CTX_DIR`
- `PENDING_PLAN_DIR`
- optional `SUPABASE_JWT_AUDIENCE`

Removed from the live runtime contract:
- `GMAIL_CLIENT_SECRET_FILE`
- `token.json`
- `client_secrets.json`

### Secrets / security actions
- Removed `token.json` and `client_secrets.json` from the runtime contract.
- Stopped returning raw OAuth tokens from credential read APIs.
- Removed hardcoded Supabase and Django secret values from settings.
- Backend operators must rotate any previously committed Google OAuth client secret and token material.

### Manual follow-up
- Recreate `.env` from `.env.example`.
- Rotate previously committed Google client credentials and any exposed token material.
- Update the Google OAuth redirect URI to `PUBLIC_BACKEND_URL + /plugins/oauth/callback/gmail/`.
- Reconnect Gmail accounts if existing credentials are no longer valid after secret rotation.

## 2026-04-17 — Supabase HS256 auth fix

### Summary
Updated the live DRF bearer-token auth path to verify Supabase access tokens as `HS256` with the shared Supabase JWT secret instead of JWKS-based `RS256` verification.

### Files changed
- `authentication/authentication.py`
- `backend/settings.py`
- `.env.example`
- `README.md`
- `SETUP.md`

### Behavior changes
- DRF API auth now verifies Supabase bearer tokens with `HS256` using `SUPABASE_JWT_SECRET`.
- The live auth path no longer depends on JWKS lookup.
- Local mirrored user emails still update when the JWT email claim changes.
- Server-side auth logs now distinguish common verification failures such as expiry, issuer, audience, and signature mismatches.

### Env changes
Added:
- `SUPABASE_JWT_SECRET`

Removed from the live auth model:
- JWKS-based Supabase token verification

### Secrets / security actions
- Backend operators must provide the Supabase JWT secret for the same project that issues the access tokens.
- The JWT secret should be handled as a sensitive runtime secret and not committed to the repo.

### Manual follow-up
- Add `SUPABASE_JWT_SECRET` to `.env`.
- Restart the backend after updating the env.
- Re-test authenticated endpoints with a current Supabase access token from the same project.

## 2026-04-17 — Direct-response planner fallback

### Summary
Added a planner-side fallback so prompts that do not need tool calls return a direct `processing_llm` response plan instead of producing an empty non-executable plan and crashing in the executor.

### Files changed
- `planner/planner.py`
- `CHANGELOG.md`

### Behavior changes
- The planner prompt now explicitly tells the model to use a single `processing_llm` step for direct-response requests that do not require tools.
- If the planner still returns an empty or otherwise non-executable plan, the backend now replaces it with a single-step direct-response plan instead of letting execution fail on an empty `final_output_var`.
- Simple prompts such as greetings can now complete through the normal planner/orchestrator path without requiring an external tool call.

### Env changes
- None.

### Secrets / security actions
- None.

### Manual follow-up
- Restart the backend to load the new planner behavior.
- Re-test `/agent/` with a direct-response prompt such as `"hello"` and with a normal tool-driven prompt to confirm both paths work.

## 2026-04-17 — Removed backend-local Docker artifacts

### Summary
Removed the repo-tracked Docker artifacts and stripped Docker-specific setup language from the backend docs so containerization can be reintroduced later from a clean baseline.

### Files changed
- `.env.example`
- `README.md`
- `SETUP.md`
- `CHANGELOG.md`
- `.dockerignore` (deleted)
- `Dockerfile` (deleted)
- `docker-compose.yml` (deleted)

### Behavior changes
- None. This change only removes repo-tracked Docker assets and Docker-specific documentation.

### Env changes
- Updated example runtime state paths to local `/tmp` defaults in `.env.example`.

### Secrets / security actions
- None.

### Manual follow-up
- Recreate any Docker setup manually if you still want containerization later.
- If your local `.env` copied the old Docker-oriented example paths, update `CHAT_CTX_DIR` and `PENDING_PLAN_DIR` as needed for your environment.

## Changelog rules

Append a new dated entry for every future backend runtime, security, config, OAuth, credential, runtime-state, infrastructure, or deployment change.

Each entry must include:
- `Summary`
- `Files changed`
- `Behavior changes`
- `Env changes`
- `Secrets / security actions`
- `Manual follow-up`

Use this file as an operational changelog only. Do not turn it into a duplicate of git history or a design document.
