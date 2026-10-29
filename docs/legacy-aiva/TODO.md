# Backend TODOs

This document captures structural gaps and remaining work in the backend.

## Priorities

- `P1`: architectural mismatch that can confuse clients or produce incorrect runtime assumptions
- `P2`: cleanup or validation gap that increases maintenance cost or risk
- `P3`: nice-to-have quality-of-life improvements

---

---

---

---

---

## ~~P2: Remove Or Rewrite The Dead Supabase Auth Middleware~~ ✓ Done 2026-05-04

---

## ~~P2: Tighten `/agent/` Request Validation And Project Scoping~~ ✓ Done 2026-05-04

---

## ~~P2: Encrypt OAuth Tokens At Rest~~ ✓ Done 2026-05-05

---

## ~~P2: Validate Full Plan Against Tool Registry Before Showing Summary~~ ✓ Done 2026-05-05

---

## ~~P2: Rate Limiting On `/agent/`~~ ✓ Done (implemented alongside P2 validation work)

---

## ~~P3: Streaming Responses / Per-Step Progress~~ ✓ Done 2026-05-07

---

## ~~P3: Multi-Step Plan Partial-Failure Reporting~~ ✓ Done 2026-05-08

---

## ~~P3: Expand `/agent/` Test Coverage~~ ✓ Done 2026-05-08

---

## ~~P3: Audit Log For Confirmed Actions~~ ✓ Done 2026-05-08

---

## ~~P2: Validate Create Endpoints With Serializers~~ ✓ Done 2026-05-08

---

## ~~P2: `ContactConnection.externalId` Global Unique Constraint~~ ✓ Done 2026-05-08

---

## ~~P2: No Rate Limiting On `/agent/stream/`~~ ✓ Done 2026-05-08

---

## ~~P3: `Task.status` Missing Choices Constraint~~ ✓ Done 2026-05-08

---

## P3: Skill Marketplace — Curated Workflow Templates

Users can browse a catalogue of pre-built workflow templates and import them as their own `SavedWorkflow` in one tap. Templates are community/team-curated Plan JSON definitions stored server-side (or shipped as fixtures) and cover common tasks: "Daily email summary", "Summarise latest news on a topic", "Draft a reply to an email thread", etc.

**Backend shape:**
- `WorkflowTemplate` model: `name`, `description`, `category` (string tag), `plan` (JSONField), `author` (optional string), `is_featured` (bool), `created_at`. No user FK — templates are global.
- `GET /agent/workflows/marketplace/` — list published templates, filterable by `?category=` and `?search=`.
- `POST /agent/workflows/marketplace/<id>/import/` — copies the template plan into a new `SavedWorkflow` owned by the authenticated user. The user can rename and edit it freely after import.
- Admin-only write surface (no public template creation in V1 — curated only).

**Frontend shape:**
- A searchable/filterable gallery of template cards (name, description, category chip, "Import" button).
- After import, the workflow appears in the user's workflow list and opens in the step builder for customisation.

**V2 extension:** Allow users to publish their own workflows to the marketplace (with a review/approval step) — community-driven skill sharing.

**Dependencies:** Requires `SavedWorkflow` (done) and the workflow step builder UI.

---

## ~~P3: Scheduled / Recurring Agent Runs~~ ✓ Done 2026-06-22

"Summarise my unread emails every morning" is a natural request. Add a `ScheduledRun` model with cron-style scheduling backed by Celery Beat or Django-Q, reusing the existing plan-and-execute path.

Implemented as `/scheduled-runs/` backed by Celery Beat, Celery workers, Redis, `ScheduledRun`, and `ScheduledRunExecution`. Scheduled runs execute saved workflows through the shared workflow runner.

---

## ~~P3: Multi-Account Plugin Support~~ ✓ Done 2026-05-07

---

## ~~P3: Plan Caching For Repeated Queries~~ ✓ Done 2026-05-07

---

## ~~P1: Google Calendar OAuth Tokens Cannot Refresh~~ ✓ Done 2026-05-10

`tools/calendar/api.py::_build_service` builds the Google `Credentials` object with
only `token`, `refresh_token`, and `token_uri`. It omits `client_id`, `client_secret`, and
`scopes`. The Google OAuth library requires all five fields to perform an automatic token refresh.
Gmail's `_build_service` passes all five correctly. When a Calendar access token expires the API
call silently fails with a 401 rather than refreshing transparently.

Fix: pass `settings.GOOGLE_CLIENT_ID`, `settings.GOOGLE_CLIENT_SECRET`, and the Calendar scopes
to `Credentials(...)` in `calendar/api.py`, matching the pattern in `gmail/api.py`.

---

## ~~P2: `calendar.delete_event` Listed In Changelog But Not Implemented~~ ✓ Done 2026-05-10

The 2026-05-03 changelog entry lists `calendar.delete_event` as a delivered tool. The actual
`tools/calendar/api.py` only registers three tools: `list_events`, `create_event`,
and `update_event`. No `calendar_delete_event` function is defined or registered. Any plan that
references `calendar.delete_event` will fail with `UnknownToolError` at validation time.

Fix: implement `calendar_delete_event(token_data, event_id, calendar_id)` using
`service.events().delete()` and register it with `requires_confirmation=True`.

---

## ~~P2: `weather.get_weather_forecast` Calls A Paid-Only OpenWeatherMap Endpoint~~ ✓ Done 2026-05-11

`tools/weather/api.py::get_weather_forecast` calls `/data/2.5/forecast/daily` which
requires a paid OWM subscription. Free API keys receive a 401. The free tier offers
`/data/2.5/forecast` (5-day forecast in 3-hour intervals) which covers the same user need.

Fix: switch to `/data/2.5/forecast`, parse the 3-hour slots into day-level summaries in the
tool, or document the paid requirement and gate the tool behind a capability check.

---

## ~~P2: `processing_llm` Has No Timeout~~ ✓ Done 2026-05-11

`tools/processing_llm/tool.py::call_processing_llm` calls OpenAI with no `timeout`
parameter. A slow or stalled OpenAI response will block the entire request indefinitely. The
planner already has a `PLANNER_TIMEOUT` setting (default 60 s) wired into every call.

Fix: read `settings.PROCESSING_LLM_TIMEOUT` (default 60 s) and pass it to
`client.chat.completions.create(timeout=...)`, matching the planner pattern.

---

## ~~P2: Weather Tool Calls Had No Timeout~~ ✓ Done 2026-06-22

`tools/weather/api.py` now passes an explicit 15-second timeout to every OpenWeatherMap
`requests.get(...)` call. This prevents a stalled weather API request from blocking an
agent or scheduled workflow execution indefinitely.

---

## ~~P2: No Cap On Plan `modify` Iterations~~ ✓ Done 2026-05-11

In `agent/views.py::run_prompt`, when `detect_intent` returns `"modify"` the agent calls
`revise_plan` and re-presents the summary. There is no limit on how many times this can happen.
A user (or a misbehaving client) can trigger unbounded LLM calls in a single session, each
costing tokens.

Fix: track a `modify_count` in the pending plan or in the session; after N revisions (e.g. 5)
respond with a message asking the user to start fresh rather than calling `revise_plan` again.

---

## ~~P3: Missing Gmail Action Tools~~ ✓ Done 2026-05-10

Users can read and send email but cannot perform basic inbox management actions. The following
tools are absent from `tools/gmail/api.py`:

- `gmail.trash_email` — move a message to Trash by `msg_id`
- `gmail.mark_read` / `gmail.mark_unread` — toggle the `UNREAD` label on a message
- `gmail.add_label` / `gmail.remove_label` — apply or remove a Gmail label by name
- `gmail.create_draft` — save a composed message as a draft without sending

All use the existing `_build_service` pattern. `trash_email` should have `requires_confirmation=True`.

---

## ~~P3: Missing `calendar.delete_event` (Tracked Separately As P2 Above)~~ ✓ Done 2026-05-10

See P2 item above — this is the primary tracking entry.

---

## ~~P3: Missing `contacts.delete` Tool~~ ✓ Done 2026-05-11

`tools/contacts/api.py` exposes `search`, `create`, and `update` but no delete.
Users cannot remove contacts they created via the agent.

Fix: add `contacts_delete(user_id, contact_id)` with `Contact.objects.get(pk=contact_id, user=user).delete()`
and register it with `requires_confirmation=True`.

---

## ~~P3: Missing `calendar.list_calendars` Tool~~ ✓ Done 2026-05-10

`calendar.list_events` defaults to `calendar_id="primary"` with no way to discover other
calendars. Users who have work, personal, and shared calendars cannot target a non-primary one
without already knowing its ID.

Fix: add `calendar.list_calendars` using `service.calendarList().list()` — returns id, summary,
and access role for each calendar. No confirmation required.

---

## ~~P3: `processing_llm` Has No `max_tokens` Cap~~ ✓ Done 2026-05-11

`call_processing_llm` passes no `max_tokens` to the OpenAI call. For large tool outputs (e.g.
50 emails fed into a summary step) the model can produce unexpectedly long responses, increasing
latency and cost.

Fix: add a `max_tokens` parameter (default e.g. 1024) and pass it through. Allow overriding per
step via the `params_schema` if needed.

---

## ~~P3: Audit Log Has No Filtering~~ ✓ Done 2026-05-11

`GET /agent/actions/` only supports `?limit=N`. There is no way to filter by `tool`, `status`,
or date range, making the endpoint nearly useless for anything beyond "show me recent actions".

Fix: add optional query params `?tool=gmail.send_email`, `?status=failed`, `?since=<ISO date>`
and apply them as ORM filters in `actions_view`.

---

## ~~P3: `PlannerUsage` Has No Retention Policy~~ ✓ Done 2026-05-11

`agent/models.py::PlannerUsage` rows are written on every planner call and never deleted. Over
time this table will grow unboundedly with no operational benefit beyond recent history.

Fix: add a management command or Celery periodic task that deletes rows older than N days
(e.g. 90 days, configurable via `PLANNER_USAGE_RETENTION_DAYS`).

---

## ~~P3: `_is_capabilities_query` Phrase List Is Hardcoded~~ ✓ Done 2026-05-11

`agent/views.py::_is_capabilities_query` matches against a fixed set of strings. Adding new
natural-language variants (e.g. "what integrations do you support") requires a code change and
redeploy.

Fix: move the phrase list to a Django setting (`CAPABILITIES_PHRASES`) so it can be updated
without a deploy, or replace the exact-match logic with a lightweight embedding/keyword check.
