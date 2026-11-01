# HTTP API

All endpoints except the OAuth callback require `Authorization: Bearer <JWT>` (see [configuration.md](configuration.md#authentication)). Unauthenticated requests currently get **403**; the stream endpoint returns **401**. All data is scoped to the authenticated user.

## Agent

| Method | Path | Description |
|---|---|---|
| `POST` | `/agent/` | Run a prompt. Body: `{"prompt": str (≤10,000 chars), "project_id": int?, "dry_run": bool?}`. Response: `{"response": str}`. |
| `POST` | `/agent/stream/` | Same body, as Server-Sent Events: `status`, `step`, then `done` (with `response`) or `error`. |
| `GET` | `/agent/actions/` | Audit log of confirmation-required tool runs. Query: `limit` (≤200), `status` (`success`\|`failed`), `since` (ISO 8601). |
| `DELETE` | `/agent/reset/<project_id>/` | Clear a conversation's history and pending plan. |
| `GET`, `POST` | `/agent/memory/` | List memories, or upsert one `{key, value}`. |
| `PUT`, `DELETE` | `/agent/memory/<id>/` | Update or delete a memory. |

**Confirmation flow.** If a plan contains a tool marked *Confirm* in [tools.md](tools.md), the agent saves the plan and replies `"<summary>\n\nShall I proceed?"`. The next prompt in the same conversation is classified as one of:
- **confirm**: the plan runs.
- **cancel**: the plan is discarded.
- **modify**: the plan is revised. After `AGENT_MAX_MODIFY_REVISIONS` revisions it is discarded.

`dry_run: true` executes read steps and previews confirmation-required steps without running them.

**Errors** use `{"error": {"code", "message", ...}}`:
- `bad_request` 400
- `unknown_tool` 400
- `not_found` 404
- `plugin_not_connected` 422 (includes `plugin`)
- `tool_execution_failed` 500 (with an LLM-written explanation)
- `internal_error` 500

The stream endpoint also returns `unauthorized` 401, `method_not_allowed` 405, and `throttled` 429. When `/agent/` itself is throttled, the response is DRF's standard 429 `{"detail": "..."}`.

## Tools

| Method | Path | Description |
|---|---|---|
| `GET` | `/tools/` | Schemas of tools the user can use: built-in tools plus tools of connected integrations. `?plugin=<id>` filters; `?plugin=system` returns built-ins only. |

## Workflows

| Method | Path | Description |
|---|---|---|
| `GET`, `POST` | `/workflows/` | List or create saved workflows `{name, description?, plan, input_schema?, project_id?}`. |
| `POST` | `/workflows/validate/` | Validate a plan and input schema without saving. |
| `GET`, `PUT`, `DELETE` | `/workflows/<id>/` | Read, update, delete. |
| `POST` | `/workflows/<id>/run/` | Execute now with `{"inputs": {...}}`. **Runs without the confirmation step.** |
| `GET`, `POST` | `/scheduled-runs/` | List or create cron schedules `{workflow_id, cron, timezone? (default UTC), name?, enabled? (default true)}`. |
| `GET`, `PUT`, `DELETE` | `/scheduled-runs/<id>/` | Read, update, delete. |
| `POST` | `/scheduled-runs/<id>/run-now/` | Queue one immediate execution. |
| `GET` | `/scheduled-runs/<id>/executions/` | Execution history. |

## Integrations (plugins)

| Method | Path | Description |
|---|---|---|
| `GET` | `/plugins/registry/` | Available integrations and their scopes. |
| `POST` | `/plugins/oauth/connect/` | `{"plugin": "<id>"}` → `{"auth_url"}`. Creates a one-time state (10-minute expiry). |
| `GET` | `/plugins/oauth/callback/<plugin>/` | **Public.** The provider redirects here. It exchanges the code, stores the result pending, and redirects to `PLUGIN_OAUTH_SUCCESS_REDIRECT?completion_token=…` or to the failure redirect. |
| `POST` | `/plugins/oauth/finalize/` | `{"plugin", "completion_token"}`. Saves the credential for the user who started the flow. Rejects any other user (403). |
| `GET` | `/plugins/credentials/` | Connected accounts (tokens never returned). |
| `GET`, `PUT`, `PATCH`, `DELETE` | `/plugins/credentials/<id>/` | Read, update metadata, or delete. |
| `POST` | `/plugins/credentials/<id>/refresh/` | Force a token refresh. |
| `POST` | `/plugins/credentials/<id>/disconnect/` | Revoke at the provider where supported, then delete. |

## Conversations, context, tasks, contacts

| Method | Path | Description |
|---|---|---|
| `GET`, `POST` | `/projects/` | Conversations ("projects"): name, enabled plugins, system prompt. |
| `GET`, `PUT`, `DELETE` | `/projects/<id>/` | |
| `GET`, `POST` | `/project-context/<project_id>/` | Conversation messages. Clients may only add `user` messages. |
| `DELETE` | `/project-context/<project_id>/clear/` | Delete all messages. |
| `POST` | `/project-context/<project_id>/trim/` | Trim history to a size. |
| `GET`, `POST` | `/tasks/<project_id>/` | Task records created by agent runs. |
| `GET`, `PATCH`, `DELETE` | `/tasks/<project_id>/<task_id>/` | |
| `POST` | `/tasks/<project_id>/<task_id>/subtasks/` | |
| `GET`, `POST` | `/contacts/` | Local contacts. |
| `GET`, `PUT`, `DELETE` | `/contacts/<id>/` | |
| `GET`, `POST` | `/contacts/<id>/connections/` | Linked accounts (email or service IDs) for a contact. |
| `GET`, `PUT`, `DELETE` | `/contacts/<id>/connections/<connection_id>/` | |

## Admin

`/admin/` is Django admin (session login). It includes models for agent actions, memories, and workflows.
