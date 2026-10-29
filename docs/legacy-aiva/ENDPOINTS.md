# Backend Endpoint Reference

This file is the canonical backend endpoint reference for [`v2/backend`](./). It is derived from the current live Django URL tree in [`backend/urls.py`](./backend/urls.py) plus the included app URL configs and view implementations.

## Conventions

- **Active** means the method+path is reachable through the current Django URL tree.
- **Non-active** means the path family is documented for orientation only and is not currently routed by the live backend.
- API auth is `Authorization: Bearer <Supabase access token>` unless an endpoint explicitly says otherwise.
- The backend does **not** expose its own login or signup endpoint. Clients authenticate with Supabase first, then call this backend with the Supabase access token.
- `/agent/` is the live planner/orchestrator entrypoint.
- Request and response descriptions reflect the code as it exists today, including quirks such as missing validation and non-standard request body usage.

## Base URL and placeholders

- Local base URL in examples: `http://localhost:8000`
- Placeholder bearer token: `<SUPABASE_ACCESS_TOKEN>`
- Example path placeholders:
  - `<projectId>`
  - `<taskId>`
  - `<contactId>`
  - `<connectionId>`
  - `<credentialId>`

## Example helpers

These helpers are reused by the concise examples below.

### TypeScript

```ts
const BASE_URL = "http://localhost:8000";
const accessToken = "<SUPABASE_ACCESS_TOKEN>";

async function apiJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  });

  if (!res.ok) {
    throw new Error(`${res.status} ${await res.text()}`);
  }

  return (await res.json()) as T;
}
```

### Swift

```swift
import Foundation

enum API {
    static let baseURL = URL(string: "http://localhost:8000")!
    static let accessToken = "<SUPABASE_ACCESS_TOKEN>"

    static func request(
        path: String,
        method: String = "GET",
        body: Data? = nil,
        contentType: String? = "application/json"
    ) async throws -> (Data, HTTPURLResponse) {
        var request = URLRequest(url: baseURL.appendingPathComponent(path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))))
        request.httpMethod = method
        request.httpBody = body
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        if let contentType {
            request.setValue(contentType, forHTTPHeaderField: "Content-Type")
        }

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw URLError(.badServerResponse)
        }
        return (data, http)
    }
}
```

### Python

```py
import requests

BASE_URL = "http://localhost:8000"
ACCESS_TOKEN = "<SUPABASE_ACCESS_TOKEN>"

def api_request(path, method="GET", json_body=None, params=None, headers=None, data=None):
    final_headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        **(headers or {}),
    }
    if json_body is not None:
        final_headers.setdefault("Content-Type", "application/json")

    response = requests.request(
        method=method,
        url=f"{BASE_URL}{path}",
        json=json_body,
        params=params,
        headers=final_headers,
        data=data,
    )
    response.raise_for_status()
    return response
```

## Shared object shapes

### Project

```json
{
  "user": 7,
  "id": 12,
  "name": "Trip planning",
  "description": "Notes for summer travel",
  "plugins": {
    "gmail": true,
    "google_drive": true
  },
  "activeContextFrom": 0,
  "createdAt": "2026-04-17T20:11:31.132Z"
}
```

### ProjectContext message

```json
{
  "id": 33,
  "role": "user",
  "content": "Book me a hotel in Tokyo",
  "sequence": 4,
  "createdAt": "2026-04-17T20:12:00.000Z"
}
```

### Task

```json
{
  "id": 21,
  "project": 12,
  "title": "Check weather",
  "description": "Look up Tokyo weather",
  "status": "pending",
  "createdAt": "2026-04-17T20:15:00.000Z",
  "updatedAt": "2026-04-17T20:15:00.000Z",
  "subTasks": [
    {
      "id": 55,
      "task": 21,
      "action": "get_weather",
      "detail": "Tokyo",
      "plugin": "weather",
      "recipients": [],
      "order": 1,
      "dependencyRequired": false,
      "confirmationRequired": false,
      "confirmationStatus": false,
      "status": "pending",
      "result": {},
      "createdAt": "2026-04-17T20:15:10.000Z"
    }
  ]
}
```

### Contact

```json
{
  "user": 7,
  "id": 3,
  "alias": "Dad",
  "firstName": "John",
  "lastName": "Doe",
  "photo": null,
  "createdAt": "2026-04-17T20:20:00.000Z"
}
```

### Contact connection

```json
{
  "contact": 3,
  "service": "Gmail",
  "alias": null,
  "externalId": "john@example.com",
  "metadata": {
    "label": "personal"
  }
}
```

### Plugin registry item

```json
{
  "key": "google_drive",
  "display": "Google Drive",
  "scopes": [
    "https://www.googleapis.com/auth/drive.readonly"
  ]
}
```

### Credential read object

```json
{
  "id": 4,
  "plugin": "google_drive",
  "account_id": "user@example.com",
  "scopes": [
    "https://www.googleapis.com/auth/drive.readonly"
  ],
  "metadata": null,
  "expires_at": "2026-04-17T22:00:00.000Z",
  "status": "active",
  "created_at": "2026-04-17T20:00:00.000Z",
  "updated_at": "2026-04-17T20:00:00.000Z",
  "last_used_at": null,
  "last_error": null
}
```

### ScheduledRun

```json
{
  "id": 9,
  "workflow_id": 5,
  "workflow_name": "Morning briefing",
  "name": "Weekday morning briefing",
  "cron": "0 7 * * 1-5",
  "timezone": "America/Edmonton",
  "enabled": true,
  "next_run_at": "2026-06-23T13:00:00+00:00",
  "last_run_at": null,
  "last_status": "",
  "last_error": null,
  "created_at": "2026-06-22T18:00:00+00:00",
  "updated_at": "2026-06-22T18:00:00+00:00"
}
```

### ScheduledRunExecution

```json
{
  "id": 14,
  "scheduled_run_id": 9,
  "workflow_id": 5,
  "status": "success",
  "started_at": "2026-06-23T13:00:02+00:00",
  "finished_at": "2026-06-23T13:00:08+00:00",
  "result": "Here is your briefing...",
  "error": null,
  "celery_task_id": "c8a29786-0d33-4214-97dd-6b02650f3f6a",
  "created_at": "2026-06-23T13:00:00+00:00"
}
```

## Active endpoints

### GET `/admin/`

- **Status:** Active
- **Purpose:** Entry point to Django admin.
- **Auth:** Django admin session/cookie auth, not DRF bearer auth.
- **Path params:** None.
- **Query params:** None.
- **Body:** None.
- **Returns:**
  - `302` redirect to `/admin/login/?next=/admin/` when not logged into Django admin.
  - `200` HTML admin page when a valid Django admin session exists.
- **Errors / notable statuses:**
  - No JSON API semantics; this is an HTML route.
- **Notes / quirks:**
  - The Django admin generates additional framework routes under `/admin/`, but the project-authored backend API does not rely on them.
  - Supabase bearer tokens do not log you into Django admin.
- **Examples:**

```ts
const res = await fetch("http://localhost:8000/admin/", { redirect: "manual" });
console.log(res.status, res.headers.get("location"));
```

```swift
let url = URL(string: "http://localhost:8000/admin/")!
let (data, response) = try await URLSession.shared.data(from: url)
print((response as? HTTPURLResponse)?.statusCode ?? -1)
print(String(data: data, encoding: .utf8) ?? "")
```

```py
import requests

response = requests.get("http://localhost:8000/admin/", allow_redirects=False)
print(response.status_code, response.headers.get("Location"))
```

### POST `/agent/`

- **Status:** Active
- **Purpose:** Main planner/orchestrator endpoint. Accepts a natural-language prompt, optionally uses tools, and returns the assistant response.
- **Auth:** Bearer token required.
- **Path params:** None.
- **Query params:** None.
- **Body:**
  - `prompt` (`string`, required): user message to the agent.
  - `project_id` (`string | number | any JSON value`, optional): namespace for DB-backed chat context and pending plans. The current implementation does not validate existence or ownership.
  - `dry_run` (`boolean`, optional, default `false`): preview mode — skips confirmation-required steps and appends a dry-run notice to the response without executing real tool calls.
- **Returns:**
  - `200` with `{"response": "<assistant text>"}`.
  - If a plan requires confirmation, the `response` value contains the plan summary followed by `Shall I proceed?`
- **Errors / notable statuses:**
  - `400` with `{"error":"No prompt provided"}` when `prompt` is empty.
  - `400` with `{"error":"Invalid JSON"}` on malformed JSON.
  - `403` DRF auth failure for missing or invalid bearer token.
  - `500` with `{"error":"..."}` for planner/orchestrator/runtime failures.
- **Notes / quirks:**
  - Conversation history and pending confirmation plans are stored in the database (DB-backed), not files. State persists across container restarts.
  - Direct-response prompts that do not need tools are currently handled through a `processing_llm` fallback plan.
- **Examples:**

```ts
type AgentResponse = { response: string };

const result = await apiJson<AgentResponse>("/agent/", {
  method: "POST",
  body: JSON.stringify({
    prompt: "hello",
    project_id: 12,
  }),
});

console.log(result.response);
```

```swift
let body = try JSONSerialization.data(withJSONObject: [
    "prompt": "hello",
    "project_id": 12
])
let (data, _) = try await API.request(path: "/agent/", method: "POST", body: body)
print(String(data: data, encoding: .utf8)!)
```

```py
response = api_request(
    "/agent/",
    method="POST",
    json_body={"prompt": "hello", "project_id": 12},
)
print(response.json())
```

## Agent — Streaming

### POST `/agent/stream/`

- **Status:** Active
- **Purpose:** Streaming variant of `POST /agent/` that emits Server-Sent Events (SSE) as each plan step completes. Use this when you want to show incremental progress instead of waiting for the full response.
- **Auth:** Bearer token required (via `Authorization` header — standard DRF auth is not applied here; the view reads the token manually).
- **Body:** Same as `POST /agent/`: `prompt`, `project_id` (optional), `dry_run` (optional).
- **Returns:** `text/event-stream` with events:
  - `event: status` — first event, contains `{"status": "planning"}` when planner starts.
  - `event: step` — one per completed step: `{"step": {"tool": "...", "output_var": "...", "result": "..."}, "step_index": N}`.
  - `event: done` — final event: `{"response": "<full assistant text>"}`.
  - `event: error` — on any failure: `{"error": "<error code>", "detail": "..."}`.
- **Errors / notable statuses:**
  - `401` JSON response when auth fails.
  - `400` JSON response when the prompt is missing or the body is invalid JSON.
- **Notes / quirks:**
  - Keep the HTTP connection open; events arrive as steps complete.
  - The full response text is in the final `done` event — intermediate `step` events contain raw step output, not the finished message.
  - Confirmation-pending plans emit a single `done` event with the "Shall I proceed?" message, the same as the sync endpoint.
- **Examples:**

```ts
const res = await fetch("http://localhost:8000/agent/stream/", {
  method: "POST",
  headers: {
    Authorization: `Bearer ${accessToken}`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({ prompt: "What is the weather in Tokyo?" }),
});

const reader = res.body!.getReader();
const decoder = new TextDecoder();
while (true) {
  const { value, done } = await reader.read();
  if (done) break;
  console.log(decoder.decode(value));
}
```

---

## Agent — Audit log

### GET `/agent/actions/`

- **Status:** Active
- **Purpose:** Return a paginated audit log of confirmed actions executed by the agent for the authenticated user.
- **Auth:** Bearer token required.
- **Query params:**
  - `limit` (`integer`, optional, default `20`, max `100`)
- **Returns:** `200` with `{"actions": [{"id", "tool", "params_summary", "status", "timestamp"}, ...]}`.
- **Notes / quirks:**
  - Only `requires_confirmation=True` steps that were explicitly confirmed are logged. Read-only tool calls are not recorded here.
- **Examples:**

```ts
const { actions } = await apiJson<{ actions: unknown[] }>("/agent/actions/");
console.log(actions);
```

```py
response = api_request("/agent/actions/")
print(response.json())
```

---

## Agent — Reset

### DELETE `/agent/reset/<projectId>/`

- **Status:** Active
- **Purpose:** Clear the agent's internal conversation history and nullify the pending plan for a project. Use this to start a fresh conversation.
- **Auth:** Bearer token required.
- **Path params:**
  - `projectId` (`integer`, required)
- **Returns:** `200` with `{"status": "ok"}`.
- **Errors / notable statuses:**
  - `404` when the project does not exist or is not owned by the user.
- **Notes / quirks:**
  - This does NOT clear the `/project-context/` transcript rows. Call `DELETE /project-context/<id>/clear/` separately if you also want to wipe the UI transcript.
- **Examples:**

```ts
await apiJson("/agent/reset/12/", { method: "DELETE" });
```

```py
response = api_request("/agent/reset/12/", method="DELETE")
print(response.json())
```

---

## Agent — Memory

### GET `/agent/memory/`

- **Status:** Active
- **Purpose:** List all persistent memories for the authenticated user.
- **Auth:** Bearer token required.
- **Returns:** `200` with `{"memories": [{"id", "key", "value", "source", "created_at", "updated_at"}, ...]}`.
- **Examples:**

```ts
const { memories } = await apiJson<{ memories: Memory[] }>("/agent/memory/");
```

---

### POST `/agent/memory/`

- **Status:** Active
- **Purpose:** Create or update a memory by key (upsert). Source is set to `manual`.
- **Auth:** Bearer token required.
- **Body:** `{"key": "home_city", "value": "Seattle"}`
- **Returns:** `201` (created) or `200` (updated) with the memory object.
- **Examples:**

```ts
await apiJson("/agent/memory/", {
  method: "POST",
  body: JSON.stringify({ key: "home_city", value: "Seattle" }),
});
```

---

### PUT `/agent/memory/<memoryId>/`

- **Status:** Active
- **Purpose:** Update an existing memory (key + value).
- **Auth:** Bearer token required.
- **Body:** `{"key": "home_city", "value": "Portland"}`
- **Returns:** `200` with the updated memory object. `404` if the memory does not belong to the user.

---

### DELETE `/agent/memory/<memoryId>/`

- **Status:** Active
- **Purpose:** Delete a memory by ID.
- **Auth:** Bearer token required.
- **Returns:** `200` with `{"status": "ok", "id": <memoryId>}`. `404` if not found or not owned by user.

---

## Tools

### GET `/tools/`

- **Status:** Active
- **Purpose:** Return all registered tool schemas. Tools are a platform-level resource used by both the agent and the workflow builder.
- **Auth:** Bearer token required.
- **Query params:**
  - `plugin` (`string`, optional) — filter to one plugin's tools (e.g. `?plugin=gmail`). Pass `system` to get tools with no plugin requirement.
- **Returns:** `200` with `{"tools": [{"name", "display_name", "description", "plugin_id", "params"}, ...]}`.
- **Notes / quirks:**
  - Returns all tools regardless of which plugins the user has connected. The caller is responsible for checking connection status via `/plugins/credentials/`.
  - `plugin_id` is `null` for system tools (`processing_llm`, `web.search`, `weather.*`).
- **Examples:**

```ts
// All tools
const { tools } = await apiJson<{ tools: unknown[] }>("/tools/");
console.log(tools.map((t: any) => t.name));

// Gmail tools only
const { tools: gmailTools } = await apiJson<{ tools: unknown[] }>("/tools/?plugin=gmail");

// System tools only (no OAuth required)
const { tools: systemTools } = await apiJson<{ tools: unknown[] }>("/tools/?plugin=system");
```

```py
response = api_request("/tools/")
print([t["name"] for t in response.json()["tools"]])

# Filter by plugin
response = api_request("/tools/", params={"plugin": "gmail"})
print([t["name"] for t in response.json()["tools"]])
```

---

## Workflows

### GET `/workflows/`

- **Status:** Active
- **Purpose:** List all saved workflows owned by the authenticated user.
- **Auth:** Bearer token required.
- **Returns:** `200` with paginated `{"count", "next", "previous", "results"}` where each result is a workflow object.
- **Examples:**

```ts
const { workflows } = await apiJson<{ workflows: unknown[] }>("/workflows/");
console.log(workflows);
```

```py
response = api_request("/workflows/")
print(response.json())
```

---

### POST `/workflows/`

- **Status:** Active
- **Purpose:** Create a new saved workflow.
- **Auth:** Bearer token required.
- **Body:**
  - `name` (`string`, required)
  - `description` (`string`, optional)
  - `plan` (`object`, required) — must be a valid Plan JSON: `{"steps": [...], "final_output_var": "...", "summary": "..."}`
  - `project_id` (`integer`, optional) — associate with a project
- **Returns:** `201` with the workflow object.
- **Errors / notable statuses:**
  - `400` when `name` or `plan` is missing.
  - `400` with `{"error": "invalid_plan", ...}` when `plan` fails Pydantic validation.
- **Examples:**

```ts
const workflow = await apiJson("/workflows/", {
  method: "POST",
  body: JSON.stringify({
    name: "Daily weather brief",
    plan: {
      steps: [
        { id: "s1", tool: "weather.get_current_weather", params: { city: "Tokyo" }, output_var: "weather" },
        { id: "s2", tool: "processing_llm", params: { instruction: "Summarise the weather", data: "$weather" }, output_var: "final" }
      ],
      final_output_var: "final",
      summary: "Get Tokyo weather and summarise"
    }
  }),
});
console.log(workflow);
```

```py
response = api_request("/workflows/", method="POST", json_body={
    "name": "Daily weather brief",
    "plan": {
        "steps": [
            {"id": "s1", "tool": "weather.get_current_weather", "params": {"city": "Tokyo"}, "output_var": "weather"},
            {"id": "s2", "tool": "processing_llm", "params": {"instruction": "Summarise the weather", "data": "$weather"}, "output_var": "final"},
        ],
        "final_output_var": "final",
        "summary": "Get Tokyo weather and summarise",
    },
})
print(response.json())
```

---

### GET `/workflows/<workflowId>/`

- **Status:** Active
- **Purpose:** Retrieve one saved workflow.
- **Auth:** Bearer token required.
- **Path params:** `workflowId` (`integer`, required)
- **Returns:** `200` with the workflow object. `404` if not found or not owned by user.
- **Examples:**

```ts
const wf = await apiJson("/workflows/5/");
console.log(wf);
```

---

### PUT `/workflows/<workflowId>/`

- **Status:** Active
- **Purpose:** Update a saved workflow. All fields are optional — only supplied fields are changed.
- **Auth:** Bearer token required.
- **Path params:** `workflowId` (`integer`, required)
- **Body:** Any subset of `name`, `description`, `plan`, `project_id`.
- **Returns:** `200` with the updated workflow object.
- **Errors / notable statuses:**
  - `400` with `{"error": "invalid_plan", ...}` if `plan` fails validation.
  - `404` if not found or not owned by user.
- **Examples:**

```ts
const updated = await apiJson("/workflows/5/", {
  method: "PUT",
  body: JSON.stringify({ name: "Renamed workflow" }),
});
```

---

### DELETE `/workflows/<workflowId>/`

- **Status:** Active
- **Purpose:** Delete a saved workflow.
- **Auth:** Bearer token required.
- **Path params:** `workflowId` (`integer`, required)
- **Returns:** `200` with `{"status": "ok", "id": <workflowId>}`. `404` if not found or not owned by user.
- **Examples:**

```ts
await apiJson("/workflows/5/", { method: "DELETE" });
```

---

### POST `/workflows/<workflowId>/run/`

- **Status:** Active
- **Purpose:** Execute the stored plan directly — no LLM re-planning. Calls `orchestrator.execute()` with the saved plan steps.
- **Auth:** Bearer token required.
- **Path params:** `workflowId` (`integer`, required)
- **Body:** None.
- **Returns:** `200` with `{"result": "<assistant response text>"}`.
- **Errors / notable statuses:**
  - `404` if the workflow does not exist or is not owned by user.
  - `500` with `{"error": "execution_error", "detail": "..."}` on orchestrator failure.
  - `500` with `{"error": "invalid_plan", ...}` if the stored plan no longer validates (e.g. tool was removed).
- **Notes / quirks:**
  - Manual workflow runs and scheduled workflow runs both use the shared `workflows.runner.run_saved_workflow(...)` service.
  - Scheduling-specific validation lives outside the runner; scheduled runs validate ownership, cron/timezone fields, plan shape, and tool names before queue/worker execution.
  - Variable references (`$output_var`) between steps work exactly as in a normal agent execution.
- **Examples:**

```ts
const result = await apiJson<{ result: string }>("/workflows/5/run/", {
  method: "POST",
});
console.log(result.result);
```

```py
response = api_request("/workflows/5/run/", method="POST")
print(response.json()["result"])
```

---

## Scheduled Runs

Scheduled runs execute existing saved workflows on a cron schedule. They do not re-plan with the LLM. V1 stores execution history in the backend DB and does not send push/email notifications.

Runtime requirement: the web server only exposes the API. Actual recurring execution requires Celery Beat, a Celery worker, and Redis to be running.

Important behavior: scheduled runs execute the saved workflow exactly as stored. Workflows containing tools with `requires_confirmation=true` can be scheduled and will execute automatically when due.

### GET `/scheduled-runs/`

- **Status:** Active
- **Purpose:** List scheduled runs owned by the authenticated user.
- **Auth:** Bearer token required.
- **Returns:** `200` with paginated `{"count", "next", "previous", "results"}` where each result is a [`ScheduledRun`](#scheduledrun).

```ts
const schedules = await apiJson("/scheduled-runs/");
console.log(schedules);
```

### POST `/scheduled-runs/`

- **Status:** Active
- **Purpose:** Create a recurring schedule for an existing saved workflow.
- **Auth:** Bearer token required.
- **Body:**
  - `workflow_id` (`integer`, required) — must belong to the authenticated user.
  - `name` (`string`, optional) — defaults to the workflow name.
  - `cron` (`string`, required) — cron expression such as `0 7 * * *`.
  - `timezone` (`string`, optional) — IANA timezone name, default `UTC`.
  - `enabled` (`boolean`, optional) — default `true`.
- **Returns:** `201` with a [`ScheduledRun`](#scheduledrun).
- **Errors / notable statuses:**
  - `400` with `invalid_schedule` for invalid cron or timezone.
  - `400` with `invalid_plan` or `unknown_tool` when the workflow cannot be scheduled.
  - `404` when the workflow does not exist or is not owned by the user.

```ts
const schedule = await apiJson("/scheduled-runs/", {
  method: "POST",
  body: JSON.stringify({
    workflow_id: 5,
    name: "Daily briefing",
    cron: "0 7 * * *",
    timezone: "America/Edmonton",
  }),
});
```

### GET `/scheduled-runs/<scheduledRunId>/`

- **Status:** Active
- **Purpose:** Retrieve one scheduled run owned by the authenticated user.
- **Auth:** Bearer token required.
- **Path params:** `scheduledRunId` (`integer`, required)
- **Returns:** `200` with a [`ScheduledRun`](#scheduledrun). `404` if not found or not owned by user.

### PUT `/scheduled-runs/<scheduledRunId>/`

- **Status:** Active
- **Purpose:** Update a scheduled run. All fields are optional.
- **Auth:** Bearer token required.
- **Path params:** `scheduledRunId` (`integer`, required)
- **Body:** Any subset of `workflow_id`, `name`, `cron`, `timezone`, `enabled`.
- **Returns:** `200` with the updated [`ScheduledRun`](#scheduledrun).
- **Notes / quirks:** Changing `cron`, `timezone`, or `enabled` recalculates `next_run_at` from the current time.

### DELETE `/scheduled-runs/<scheduledRunId>/`

- **Status:** Active
- **Purpose:** Delete a scheduled run and its execution history.
- **Auth:** Bearer token required.
- **Path params:** `scheduledRunId` (`integer`, required)
- **Returns:** `200` with `{"status": "ok", "id": <scheduledRunId>}`.

### POST `/scheduled-runs/<scheduledRunId>/run-now/`

- **Status:** Active
- **Purpose:** Queue one immediate execution using the same worker path as recurring runs.
- **Auth:** Bearer token required.
- **Path params:** `scheduledRunId` (`integer`, required)
- **Returns:** `202` with `{"execution": <ScheduledRunExecution>}`.
- **Errors / notable statuses:**
  - `503` with `queue_unavailable` if the backend cannot enqueue the Celery task. The execution row is marked `failed`.
- **Notes / quirks:** This queues work through Celery. If the worker is not running but Redis accepts the task, the execution remains queued until a worker starts.

### GET `/scheduled-runs/<scheduledRunId>/executions/`

- **Status:** Active
- **Purpose:** List execution history for a scheduled run.
- **Auth:** Bearer token required.
- **Path params:** `scheduledRunId` (`integer`, required)
- **Returns:** `200` with paginated `{"count", "next", "previous", "results"}` where each result is a [`ScheduledRunExecution`](#scheduledrunexecution).

---

## Projects

### GET `/projects/`

- **Status:** Active
- **Purpose:** List all projects owned by the authenticated user.
- **Auth:** Bearer token required.
- **Path params:** None.
- **Query params:** None.
- **Body:** None.
- **Returns:** `200` with an array of [`Project`](#project) objects.
- **Errors / notable statuses:**
  - `403` DRF auth failure for missing or invalid bearer token.
- **Notes / quirks:**
  - Only the current user’s projects are returned.
- **Examples:**

```ts
const projects = await apiJson<Array<{
  user: number;
  id: number;
  name: string;
  description: string;
  plugins: Record<string, unknown>;
  activeContextFrom: number;
  createdAt: string;
}>>("/projects/");

console.log(projects);
```

```swift
let (data, _) = try await API.request(path: "/projects/")
print(String(data: data, encoding: .utf8)!)
```

```py
response = api_request("/projects/")
print(response.json())
```

### POST `/projects/`

- **Status:** Active
- **Purpose:** Create a new project for the authenticated user.
- **Auth:** Bearer token required.
- **Path params:** None.
- **Query params:** None.
- **Body:**
  - `name` (`string`, required)
  - `description` (`string`, optional, default `""`)
  - `plugins` (`object`, optional, default `{}`)
  - `activeContextFrom` (`integer`, optional, default `0`)
- **Returns:** `201` with the created [`Project`](#project) object.
- **Errors / notable statuses:**
  - `403` DRF auth failure.
  - Current implementation may raise `500` if `name` is omitted because it uses `request.data["name"]`.
- **Notes / quirks:**
  - `user` is server-owned and ignored from client input.
- **Examples:**

```ts
const created = await apiJson<{
  user: number;
  id: number;
  name: string;
  description: string;
  plugins: Record<string, unknown>;
  activeContextFrom: number;
  createdAt: string;
}>("/projects/", {
  method: "POST",
  body: JSON.stringify({
    name: "Trip planning",
    description: "Notes for summer travel",
    plugins: { gmail: true, google_drive: true },
    activeContextFrom: 0,
  }),
});

console.log(created.id);
```

```swift
let body = try JSONSerialization.data(withJSONObject: [
    "name": "Trip planning",
    "description": "Notes for summer travel",
    "plugins": ["gmail": true, "google_drive": true],
    "activeContextFrom": 0
])
let (data, _) = try await API.request(path: "/projects/", method: "POST", body: body)
print(String(data: data, encoding: .utf8)!)
```

```py
response = api_request(
    "/projects/",
    method="POST",
    json_body={
        "name": "Trip planning",
        "description": "Notes for summer travel",
        "plugins": {"gmail": True, "google_drive": True},
        "activeContextFrom": 0,
    },
)
print(response.json())
```

### GET `/projects/<projectId>/`

- **Status:** Active
- **Purpose:** Retrieve one project owned by the authenticated user.
- **Auth:** Bearer token required.
- **Path params:**
  - `projectId` (`integer`, required)
- **Query params:** None.
- **Body:** None.
- **Returns:** `200` with the matching [`Project`](#project) object.
- **Errors / notable statuses:**
  - `403` DRF auth failure.
  - `404` when the project does not exist or is not owned by the user.
- **Notes / quirks:**
  - Ownership is enforced.
- **Examples:**

```ts
const project = await apiJson<{
  user: number;
  id: number;
  name: string;
  description: string;
  plugins: Record<string, unknown>;
  activeContextFrom: number;
  createdAt: string;
}>("/projects/12/");

console.log(project.name);
```

```swift
let (data, _) = try await API.request(path: "/projects/12/")
print(String(data: data, encoding: .utf8)!)
```

```py
response = api_request("/projects/12/")
print(response.json())
```

### PUT `/projects/<projectId>/`

- **Status:** Active
- **Purpose:** Update a project.
- **Auth:** Bearer token required.
- **Path params:**
  - `projectId` (`integer`, required)
- **Query params:** None.
- **Body:** Any subset of:
  - `name` (`string`)
  - `description` (`string`)
  - `plugins` (`object`)
  - `activeContextFrom` (`integer`)
- **Returns:** `200` with the updated [`Project`](#project) object.
- **Errors / notable statuses:**
  - `403` DRF auth failure.
  - `404` when the project does not exist or is not owned by the user.
- **Notes / quirks:**
  - This behaves like a partial update even though it is `PUT`.
- **Examples:**

```ts
const updated = await apiJson<{
  user: number;
  id: number;
  name: string;
  description: string;
  plugins: Record<string, unknown>;
  activeContextFrom: number;
  createdAt: string;
}>("/projects/12/", {
  method: "PUT",
  body: JSON.stringify({
    description: "Updated description",
    activeContextFrom: 10,
  }),
});

console.log(updated.description);
```

```swift
let body = try JSONSerialization.data(withJSONObject: [
    "description": "Updated description",
    "activeContextFrom": 10
])
let (data, _) = try await API.request(path: "/projects/12/", method: "PUT", body: body)
print(String(data: data, encoding: .utf8)!)
```

```py
response = api_request(
    "/projects/12/",
    method="PUT",
    json_body={"description": "Updated description", "activeContextFrom": 10},
)
print(response.json())
```

### DELETE `/projects/<projectId>/`

- **Status:** Active
- **Purpose:** Delete a project.
- **Auth:** Bearer token required.
- **Path params:**
  - `projectId` (`integer`, required)
- **Query params:** None.
- **Body:** None.
- **Returns:** `204` with an empty body.
- **Errors / notable statuses:**
  - `403` DRF auth failure.
  - `404` when the project does not exist or is not owned by the user.
- **Notes / quirks:**
  - Deleting a project cascades to related rows such as tasks and project context.
- **Examples:**

```ts
const res = await fetch("http://localhost:8000/projects/12/", {
  method: "DELETE",
  headers: { Authorization: `Bearer ${accessToken}` },
});
console.log(res.status);
```

```swift
let (_, response) = try await API.request(path: "/projects/12/", method: "DELETE", body: nil, contentType: nil)
print(response.statusCode)
```

```py
response = api_request("/projects/12/", method="DELETE")
print(response.status_code)
```

## Project context

### GET `/project-context/<projectId>/`

- **Status:** Active
- **Purpose:** List DB-backed context messages for a project in ascending `sequence` order.
- **Auth:** Bearer token required.
- **Path params:**
  - `projectId` (`integer`, required)
- **Query params:** None.
- **Body:** None.
- **Returns:** `200` with an array of [`ProjectContext message`](#projectcontext-message) objects.
- **Errors / notable statuses:**
  - `403` DRF auth failure.
  - `404` when the project does not exist or is not owned by the user.
- **Notes / quirks:**
  - This is a DB-backed project transcript API used for displaying conversation history in the UI.
  - `/agent/` also stores its own DB-backed chat context (via `ProjectContext` model) that drives the planner — the two stores are separate.
- **Examples:**

```ts
const messages = await apiJson<Array<{
  id: number;
  role: string;
  content: string;
  sequence: number;
  createdAt: string;
}>>("/project-context/12/");

console.log(messages);
```

```swift
let (data, _) = try await API.request(path: "/project-context/12/")
print(String(data: data, encoding: .utf8)!)
```

```py
response = api_request("/project-context/12/")
print(response.json())
```

### POST `/project-context/<projectId>/`

- **Status:** Active
- **Purpose:** Append a context message to a project and assign the next `sequence` value.
- **Auth:** Bearer token required.
- **Path params:**
  - `projectId` (`integer`, required)
- **Query params:** None.
- **Body:**
  - `role` (`string`, required): must be `user` for client-created rows.
  - `content` (`string`, required): max `10000` characters.
- **Returns:** `201` with the created [`ProjectContext message`](#projectcontext-message) object.
- **Errors / notable statuses:**
  - `403` DRF auth failure.
  - `400` when `role` is not `user`, required fields are missing, or `content` is too long.
  - `404` when the project does not exist or is not owned by the user.
- **Notes / quirks:**
  - `GET` can return backend-created `assistant`, `system`, or `tool` rows if internal backend writers create them.
  - `POST` is intentionally limited to `user` rows so clients cannot forge backend-owned transcript roles.
- **Examples:**

```ts
const message = await apiJson<{
  id: number;
  role: string;
  content: string;
  sequence: number;
  createdAt: string;
}>("/project-context/12/", {
  method: "POST",
  body: JSON.stringify({
    role: "user",
    content: "Book me a hotel in Tokyo",
  }),
});

console.log(message.sequence);
```

```swift
let body = try JSONSerialization.data(withJSONObject: [
    "role": "user",
    "content": "Book me a hotel in Tokyo"
])
let (data, _) = try await API.request(path: "/project-context/12/", method: "POST", body: body)
print(String(data: data, encoding: .utf8)!)
```

```py
response = api_request(
    "/project-context/12/",
    method="POST",
    json_body={"role": "user", "content": "Book me a hotel in Tokyo"},
)
print(response.json())
```

### DELETE `/project-context/<projectId>/clear/`

- **Status:** Active
- **Purpose:** Delete all DB-backed context messages for a project.
- **Auth:** Bearer token required.
- **Path params:**
  - `projectId` (`integer`, required)
- **Query params:** None.
- **Body:** None.
- **Returns:** `204` with an empty body.
- **Errors / notable statuses:**
  - `403` DRF auth failure.
  - `404` when the project does not exist or is not owned by the user.
- **Notes / quirks:**
  - This clears only the project-context transcript rows. To also clear the `/agent/` chat context and pending plan, call `DELETE /agent/reset/<projectId>/`.
- **Examples:**

```ts
const res = await fetch("http://localhost:8000/project-context/12/clear/", {
  method: "DELETE",
  headers: { Authorization: `Bearer ${accessToken}` },
});
console.log(res.status);
```

```swift
let (_, response) = try await API.request(path: "/project-context/12/clear/", method: "DELETE", body: nil, contentType: nil)
print(response.statusCode)
```

```py
response = api_request("/project-context/12/clear/", method="DELETE")
print(response.status_code)
```

### POST `/project-context/<projectId>/trim/`

- **Status:** Active
- **Purpose:** Keep only the last `N` DB-backed context messages for a project.
- **Auth:** Bearer token required.
- **Path params:**
  - `projectId` (`integer`, required)
- **Query params:** None.
- **Body:**
  - `keep_last` (`integer`, optional, default `50`)
- **Returns:** `200` with `{"kept": <keep_last>}`.
- **Errors / notable statuses:**
  - `400` with `{"error":"keep_last must be an integer"}` when parsing fails.
  - `400` with `{"error":"keep_last must be at least 1"}` when the value is less than 1.
  - `403` DRF auth failure.
  - `404` when the project does not exist or is not owned by the user.
- **Notes / quirks:**
  - The response echoes the requested `keep_last` value, not the actual number of rows remaining.
- **Examples:**

```ts
const result = await apiJson<{ kept: number }>("/project-context/12/trim/", {
  method: "POST",
  body: JSON.stringify({ keep_last: 20 }),
});

console.log(result.kept);
```

```swift
let body = try JSONSerialization.data(withJSONObject: ["keep_last": 20])
let (data, _) = try await API.request(path: "/project-context/12/trim/", method: "POST", body: body)
print(String(data: data, encoding: .utf8)!)
```

```py
response = api_request(
    "/project-context/12/trim/",
    method="POST",
    json_body={"keep_last": 20},
)
print(response.json())
```

## Tasks

### GET `/tasks/<projectId>/`

- **Status:** Active
- **Purpose:** List tasks for a project owned by the authenticated user.
- **Auth:** Bearer token required.
- **Path params:**
  - `projectId` (`integer`, required)
- **Query params:** None.
- **Body:** None.
- **Returns:** `200` with an array of [`Task`](#task) objects.
- **Errors / notable statuses:**
  - `403` DRF auth failure.
- **Notes / quirks:**
  - The queryset is scoped through `project__user=request.user`.
  - Task serialization includes nested `subTasks`.
  - Unlike many other project-scoped endpoints, this view does not call `get_object_or_404` on the project first. A missing or foreign project currently returns `200` with `[]` instead of `404`.
- **Examples:**

```ts
const tasks = await apiJson<Array<Record<string, unknown>>>("/tasks/12/");
console.log(tasks);
```

```swift
let (data, _) = try await API.request(path: "/tasks/12/")
print(String(data: data, encoding: .utf8)!)
```

```py
response = api_request("/tasks/12/")
print(response.json())
```

### POST `/tasks/<projectId>/`

- **Status:** Active
- **Purpose:** Create a task under a project.
- **Auth:** Bearer token required.
- **Path params:**
  - `projectId` (`integer`, required)
- **Query params:** None.
- **Body:**
  - `title` (`string`, required)
  - `description` (`string`, optional, default `""`)
- **Returns:** `201` with the created [`Task`](#task) object.
- **Errors / notable statuses:**
  - `403` DRF auth failure.
  - `404` when the project does not exist or is not owned by the user.
  - Current implementation may raise `500` if `title` is omitted because it uses `request.data["title"]`.
- **Notes / quirks:**
  - New tasks default to `status = "pending"`.
- **Examples:**

```ts
const task = await apiJson<Record<string, unknown>>("/tasks/12/", {
  method: "POST",
  body: JSON.stringify({
    title: "Check weather",
    description: "Look up Tokyo weather",
  }),
});

console.log(task);
```

```swift
let body = try JSONSerialization.data(withJSONObject: [
    "title": "Check weather",
    "description": "Look up Tokyo weather"
])
let (data, _) = try await API.request(path: "/tasks/12/", method: "POST", body: body)
print(String(data: data, encoding: .utf8)!)
```

```py
response = api_request(
    "/tasks/12/",
    method="POST",
    json_body={"title": "Check weather", "description": "Look up Tokyo weather"},
)
print(response.json())
```

### GET `/tasks/<projectId>/<taskId>/`

- **Status:** Active
- **Purpose:** Retrieve a single task.
- **Auth:** Bearer token required.
- **Path params:**
  - `projectId` (`integer`, required)
  - `taskId` (`integer`, required)
- **Query params:** None.
- **Body:** None.
- **Returns:** `200` with the matching [`Task`](#task) object.
- **Errors / notable statuses:**
  - `403` DRF auth failure.
  - `404` when the task is missing or not owned through the project.
- **Examples:**

```ts
const task = await apiJson<Record<string, unknown>>("/tasks/12/21/");
console.log(task);
```

```swift
let (data, _) = try await API.request(path: "/tasks/12/21/")
print(String(data: data, encoding: .utf8)!)
```

```py
response = api_request("/tasks/12/21/")
print(response.json())
```

### DELETE `/tasks/<projectId>/<taskId>/`

- **Status:** Active
- **Purpose:** Delete a single task.
- **Auth:** Bearer token required.
- **Path params:**
  - `projectId` (`integer`, required)
  - `taskId` (`integer`, required)
- **Query params:** None.
- **Body:** None.
- **Returns:** `204` with an empty body.
- **Errors / notable statuses:**
  - `403` DRF auth failure.
  - `404` when the task is missing or not owned through the project.
- **Examples:**

```ts
const res = await fetch("http://localhost:8000/tasks/12/21/", {
  method: "DELETE",
  headers: { Authorization: `Bearer ${accessToken}` },
});
console.log(res.status);
```

```swift
let (_, response) = try await API.request(path: "/tasks/12/21/", method: "DELETE", body: nil, contentType: nil)
print(response.statusCode)
```

```py
response = api_request("/tasks/12/21/", method="DELETE")
print(response.status_code)
```

### POST `/tasks/<projectId>/<taskId>/subtasks/`

- **Status:** Active
- **Purpose:** Create a subtask under a task.
- **Auth:** Bearer token required.
- **Path params:**
  - `projectId` (`integer`, required)
  - `taskId` (`integer`, required)
- **Query params:** None.
- **Body:**
  - `action` (`string`, required)
  - `plugin` (`string`, required)
  - `order` (`integer`, required)
  - `detail` (`string`, optional, default `""`)
  - `recipients` (`array`, optional, default `[]`)
- **Returns:** `201` with the created subtask object. The response includes model defaults such as:
  - `dependencyRequired = false`
  - `confirmationRequired = false`
  - `confirmationStatus = false`
  - `status = "pending"`
  - `result = {}`
- **Errors / notable statuses:**
  - `403` DRF auth failure.
  - `404` when the task is missing or not owned through the project.
  - Current implementation may raise `500` if `action`, `plugin`, or `order` is omitted.
- **Notes / quirks:**
  - `(task, order)` must be unique.
- **Examples:**

```ts
const subtask = await apiJson<Record<string, unknown>>("/tasks/12/21/subtasks/", {
  method: "POST",
  body: JSON.stringify({
    action: "get_weather",
    plugin: "weather",
    order: 1,
    detail: "Tokyo",
    recipients: [],
  }),
});

console.log(subtask);
```

```swift
let body = try JSONSerialization.data(withJSONObject: [
    "action": "get_weather",
    "plugin": "weather",
    "order": 1,
    "detail": "Tokyo",
    "recipients": []
])
let (data, _) = try await API.request(path: "/tasks/12/21/subtasks/", method: "POST", body: body)
print(String(data: data, encoding: .utf8)!)
```

```py
response = api_request(
    "/tasks/12/21/subtasks/",
    method="POST",
    json_body={
        "action": "get_weather",
        "plugin": "weather",
        "order": 1,
        "detail": "Tokyo",
        "recipients": [],
    },
)
print(response.json())
```

## Contacts

### GET `/contacts/`

- **Status:** Active
- **Purpose:** List contacts for the authenticated user, optionally filtered by a search string.
- **Auth:** Bearer token required.
- **Path params:** None.
- **Query params:**
  - `search` (`string`, optional)
- **Body:** None.
- **Returns:** `200` with an array of [`Contact`](#contact) objects.
- **Errors / notable statuses:**
  - `403` DRF auth failure.
- **Notes / quirks:**
  - Filtering is delegated to `contacts.services.get_filtered_contacts`.
  - Search currently checks only `firstName` and `lastName`, not `alias`.
  - Exact first-name/last-name matches are preferred; substring matches are used only when no exact matches exist.
- **Examples:**

```ts
const contacts = await apiJson<Array<Record<string, unknown>>>("/contacts/?search=dad");
console.log(contacts);
```

```swift
let url = URL(string: "http://localhost:8000/contacts/?search=dad")!
var request = URLRequest(url: url)
request.setValue("Bearer \(API.accessToken)", forHTTPHeaderField: "Authorization")
let (data, _) = try await URLSession.shared.data(for: request)
print(String(data: data, encoding: .utf8)!)
```

```py
response = api_request("/contacts/", params={"search": "dad"})
print(response.json())
```

### POST `/contacts/`

- **Status:** Active
- **Purpose:** Create a contact.
- **Auth:** Bearer token required.
- **Path params:** None.
- **Query params:** None.
- **Body:**
  - `firstName` (`string`, required)
  - `lastName` (`string`, required in practice)
  - `alias` (`string`, optional)
  - `photo` (file or value accepted by DRF parser, optional)
- **Returns:** `201` with the created [`Contact`](#contact) object.
- **Errors / notable statuses:**
  - `403` DRF auth failure.
  - Current implementation may raise `500` if `firstName` or `lastName` is omitted.
- **Notes / quirks:**
  - `lastName` is optional in the serializer/model but required by the current view code because it uses `request.data["lastName"]`.
- **Examples:**

```ts
const contact = await apiJson<Record<string, unknown>>("/contacts/", {
  method: "POST",
  body: JSON.stringify({
    firstName: "John",
    lastName: "Doe",
    alias: "Dad",
  }),
});

console.log(contact);
```

```swift
let body = try JSONSerialization.data(withJSONObject: [
    "firstName": "John",
    "lastName": "Doe",
    "alias": "Dad"
])
let (data, _) = try await API.request(path: "/contacts/", method: "POST", body: body)
print(String(data: data, encoding: .utf8)!)
```

```py
response = api_request(
    "/contacts/",
    method="POST",
    json_body={"firstName": "John", "lastName": "Doe", "alias": "Dad"},
)
print(response.json())
```

### GET `/contacts/<contactId>/`

- **Status:** Active
- **Purpose:** Retrieve a contact by ID.
- **Auth:** Bearer token required.
- **Path params:**
  - `contactId` (`integer`, required)
- **Query params:** None.
- **Body:** None.
- **Returns:** `200` with the matching [`Contact`](#contact) object.
- **Errors / notable statuses:**
  - `403` DRF auth failure.
  - `404` when the contact does not exist or is not owned by the user.
- **Examples:**

```ts
const contact = await apiJson<Record<string, unknown>>("/contacts/3/");
console.log(contact);
```

```swift
let (data, _) = try await API.request(path: "/contacts/3/")
print(String(data: data, encoding: .utf8)!)
```

```py
response = api_request("/contacts/3/")
print(response.json())
```

### PUT `/contacts/<contactId>/`

- **Status:** Active
- **Purpose:** Update a contact.
- **Auth:** Bearer token required.
- **Path params:**
  - `contactId` (`integer`, required)
- **Query params:** None.
- **Body:** Any subset of:
  - `firstName`
  - `lastName`
  - `alias`
  - `photo`
- **Returns:** `200` with the updated [`Contact`](#contact) object.
- **Errors / notable statuses:**
  - `403` DRF auth failure.
  - `404` when the contact does not exist or is not owned by the user.
- **Notes / quirks:**
  - This behaves like a partial update even though it is `PUT`.
- **Examples:**

```ts
const updated = await apiJson<Record<string, unknown>>("/contacts/3/", {
  method: "PUT",
  body: JSON.stringify({ alias: "Dad" }),
});

console.log(updated);
```

```swift
let body = try JSONSerialization.data(withJSONObject: ["alias": "Dad"])
let (data, _) = try await API.request(path: "/contacts/3/", method: "PUT", body: body)
print(String(data: data, encoding: .utf8)!)
```

```py
response = api_request("/contacts/3/", method="PUT", json_body={"alias": "Dad"})
print(response.json())
```

### DELETE `/contacts/<contactId>/`

- **Status:** Active
- **Purpose:** Delete a contact.
- **Auth:** Bearer token required.
- **Path params:**
  - `contactId` (`integer`, required)
- **Query params:** None.
- **Body:** None.
- **Returns:** `204` with an empty body.
- **Errors / notable statuses:**
  - `403` DRF auth failure.
  - `404` when the contact does not exist or is not owned by the user.
- **Examples:**

```ts
const res = await fetch("http://localhost:8000/contacts/3/", {
  method: "DELETE",
  headers: { Authorization: `Bearer ${accessToken}` },
});
console.log(res.status);
```

```swift
let (_, response) = try await API.request(path: "/contacts/3/", method: "DELETE", body: nil, contentType: nil)
print(response.statusCode)
```

```py
response = api_request("/contacts/3/", method="DELETE")
print(response.status_code)
```

### GET `/contacts/<contactId>/connections/`

- **Status:** Active
- **Purpose:** List connection records for a contact.
- **Auth:** Bearer token required.
- **Path params:**
  - `contactId` (`integer`, required)
- **Query params:** None.
- **Body:** None.
- **Returns:** `200` with an array of [`Contact connection`](#contact-connection) objects.
- **Errors / notable statuses:**
  - `403` DRF auth failure.
  - `404` when the contact does not exist or is not owned by the user.
- **Notes / quirks:**
  - Connection objects do **not** include their own `id` in the serializer response, even though the detail route requires `<connectionId>`.
- **Examples:**

```ts
const connections = await apiJson<Array<Record<string, unknown>>>("/contacts/3/connections/");
console.log(connections);
```

```swift
let (data, _) = try await API.request(path: "/contacts/3/connections/")
print(String(data: data, encoding: .utf8)!)
```

```py
response = api_request("/contacts/3/connections/")
print(response.json())
```

### POST `/contacts/<contactId>/connections/`

- **Status:** Active
- **Purpose:** Create a connection record for a contact.
- **Auth:** Bearer token required.
- **Path params:**
  - `contactId` (`integer`, required)
- **Query params:** None.
- **Body:**
  - `service` (`string`, required)
  - `externalId` (`string`, required)
  - `metadata` (`object`, optional)
- **Returns:** `201` with the created [`Contact connection`](#contact-connection) object.
- **Errors / notable statuses:**
  - `400` with `{"error":"Plugin not available"}` when `service` is not in [`plugins.json`](./plugins.json).
  - `403` DRF auth failure.
  - `404` when the contact does not exist or is not owned by the user.
  - Current implementation may raise `500` if `service` or `externalId` is omitted.
- **Notes / quirks:**
  - The current allowed service list comes from [`plugins.json`](./plugins.json), which currently contains only `"Gmail"`.
  - This `service` value is a contact-connection label and is case-sensitive in practice. It is separate from the OAuth plugin key used by `/plugins/oauth/connect/`, which is currently lowercase `gmail`.
  - `alias` exists on the model/serializer but cannot be set through this create view.
- **Examples:**

```ts
const connection = await apiJson<Record<string, unknown>>("/contacts/3/connections/", {
  method: "POST",
  body: JSON.stringify({
    service: "Gmail",
    externalId: "john@example.com",
    metadata: { label: "personal" },
  }),
});

console.log(connection);
```

```swift
let body = try JSONSerialization.data(withJSONObject: [
    "service": "Gmail",
    "externalId": "john@example.com",
    "metadata": ["label": "personal"]
])
let (data, _) = try await API.request(path: "/contacts/3/connections/", method: "POST", body: body)
print(String(data: data, encoding: .utf8)!)
```

```py
response = api_request(
    "/contacts/3/connections/",
    method="POST",
    json_body={
        "service": "Gmail",
        "externalId": "john@example.com",
        "metadata": {"label": "personal"},
    },
)
print(response.json())
```

### GET `/contacts/<contactId>/connections/<connectionId>/`

- **Status:** Active
- **Purpose:** Retrieve one contact connection record.
- **Auth:** Bearer token required.
- **Path params:**
  - `contactId` (`integer`, required)
  - `connectionId` (`integer`, required)
- **Query params:** None.
- **Body:**
  - `service` (`string`, required by the current implementation)
- **Returns:** `200` with the matching [`Contact connection`](#contact-connection) object.
- **Errors / notable statuses:**
  - `403` DRF auth failure.
  - `404` when the contact or connection does not exist, is not owned by the user, or the body `service` does not match.
  - Current implementation may raise `500` if `service` is omitted.
- **Notes / quirks:**
  - This endpoint requires a request body on `GET`, which is non-standard and may not work in browser `fetch` or with some proxies/intermediaries.
  - The route already has `connectionId`, but the view still requires `service` in the body.
  - The `service` value is matched exactly against the stored connection row.
- **Examples:**

```ts
import axios from "axios";

const response = await axios.request({
  url: "http://localhost:8000/contacts/3/connections/9/",
  method: "GET",
  headers: { Authorization: `Bearer ${accessToken}` },
  data: { service: "Gmail" },
});

console.log(response.data);
```

```swift
let body = try JSONSerialization.data(withJSONObject: ["service": "Gmail"])
let (data, _) = try await API.request(path: "/contacts/3/connections/9/", method: "GET", body: body)
print(String(data: data, encoding: .utf8)!)
```

```py
response = api_request(
    "/contacts/3/connections/9/",
    method="GET",
    json_body={"service": "Gmail"},
)
print(response.json())
```

### PUT `/contacts/<contactId>/connections/<connectionId>/`

- **Status:** Active
- **Purpose:** Update one contact connection record.
- **Auth:** Bearer token required.
- **Path params:**
  - `contactId` (`integer`, required)
  - `connectionId` (`integer`, required)
- **Query params:** None.
- **Body:**
  - `service` (`string`, required)
  - `externalId` (`string`, optional)
  - `metadata` (`object`, optional)
- **Returns:** `200` with the updated [`Contact connection`](#contact-connection) object.
- **Errors / notable statuses:**
  - `403` DRF auth failure.
  - `404` when the contact or connection does not exist, is not owned by the user, or the body `service` does not match.
  - Current implementation may raise `500` if `service` is omitted.
- **Notes / quirks:**
  - `alias` exists on the model but is not updated by this view.
  - The body `service` is used to look up the existing row before the update happens, so it must match the current stored service value.
- **Examples:**

```ts
const updated = await apiJson<Record<string, unknown>>("/contacts/3/connections/9/", {
  method: "PUT",
  body: JSON.stringify({
    service: "Gmail",
    externalId: "john.doe@example.com",
    metadata: { label: "updated" },
  }),
});

console.log(updated);
```

```swift
let body = try JSONSerialization.data(withJSONObject: [
    "service": "Gmail",
    "externalId": "john.doe@example.com",
    "metadata": ["label": "updated"]
])
let (data, _) = try await API.request(path: "/contacts/3/connections/9/", method: "PUT", body: body)
print(String(data: data, encoding: .utf8)!)
```

```py
response = api_request(
    "/contacts/3/connections/9/",
    method="PUT",
    json_body={
        "service": "Gmail",
        "externalId": "john.doe@example.com",
        "metadata": {"label": "updated"},
    },
)
print(response.json())
```

### DELETE `/contacts/<contactId>/connections/<connectionId>/`

- **Status:** Active
- **Purpose:** Delete one contact connection record.
- **Auth:** Bearer token required.
- **Path params:**
  - `contactId` (`integer`, required)
  - `connectionId` (`integer`, required)
- **Query params:** None.
- **Body:**
  - `service` (`string`, required by the current implementation)
- **Returns:** `204` with an empty body.
- **Errors / notable statuses:**
  - `403` DRF auth failure.
  - `404` when the contact or connection does not exist, is not owned by the user, or the body `service` does not match.
  - Current implementation may raise `500` if `service` is omitted.
- **Notes / quirks:**
  - Requiring a body on `DELETE` is unusual but generally easier to send than a `GET` body.
  - The body `service` must match the stored service value or the delete will miss the row and return `404`.
- **Examples:**

```ts
const res = await fetch("http://localhost:8000/contacts/3/connections/9/", {
  method: "DELETE",
  headers: {
    Authorization: `Bearer ${accessToken}`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({ service: "Gmail" }),
});

console.log(res.status);
```

```swift
let body = try JSONSerialization.data(withJSONObject: ["service": "Gmail"])
let (_, response) = try await API.request(path: "/contacts/3/connections/9/", method: "DELETE", body: body)
print(response.statusCode)
```

```py
response = api_request(
    "/contacts/3/connections/9/",
    method="DELETE",
    json_body={"service": "Gmail"},
)
print(response.status_code)
```

## Plugins

### GET `/plugins/registry/`

- **Status:** Active
- **Purpose:** List plugin definitions that the backend currently knows about.
- **Auth:** Bearer token required.
- **Path params:** None.
- **Query params:** None.
- **Body:** None.
- **Returns:** `200` with an array of [`Plugin registry item`](#plugin-registry-item) objects.
- **Errors / notable statuses:**
  - `403` DRF auth failure.
- **Notes / quirks:**
  - The live registry currently contains `gmail`, `google_calendar`, `google_drive`, `google_contacts`, `outlook`, and `outlook_calendar`.
- **Examples:**

```ts
const plugins = await apiJson<Array<{
  key: string;
  display: string;
  scopes: string[];
}>>("/plugins/registry/");

console.log(plugins);
```

```swift
let (data, _) = try await API.request(path: "/plugins/registry/")
print(String(data: data, encoding: .utf8)!)
```

```py
response = api_request("/plugins/registry/")
print(response.json())
```

### POST `/plugins/oauth/connect/`

- **Status:** Active
- **Purpose:** Start an OAuth flow and receive a provider `auth_url`.
- **Auth:** Bearer token required.
- **Path params:** None.
- **Query params:** None.
- **Body:**
  - `plugin` (`string`, required). Current registered keys are `gmail`, `google_calendar`, `google_drive`, `google_contacts`, `outlook`, and `outlook_calendar`.
- **Returns:** `200` with `{"auth_url":"<provider authorize URL>"}`.
- **Errors / notable statuses:**
  - `400` with `{"detail":"Unknown plugin"}` when the key is not in the plugin registry.
  - `500` with `{"detail":"<ENV_NAME> not configured"}` when the plugin’s client ID env var is missing.
  - `403` DRF auth failure.
- **Notes / quirks:**
  - The returned URL already includes a signed one-time state, redirect URI, scopes, and provider-specific params.
  - The signed state contains an opaque nonce; the backend stores the initiating user/plugin in `PluginOAuthStates`.
  - Current Google-backed plugin keys are lowercase `gmail`, `google_calendar`, `google_drive`, and `google_contacts`; Microsoft-backed keys are `outlook` and `outlook_calendar`.
  - This backend plugin key is distinct from the separate contact-connection `service` value `"Gmail"` used under `/contacts/.../connections/`.
- **Examples:**

```ts
const result = await apiJson<{ auth_url: string }>("/plugins/oauth/connect/", {
  method: "POST",
  body: JSON.stringify({ plugin: "google_drive" }),
});

console.log(result.auth_url);
```

```swift
let body = try JSONSerialization.data(withJSONObject: ["plugin": "google_drive"])
let (data, _) = try await API.request(path: "/plugins/oauth/connect/", method: "POST", body: body)
print(String(data: data, encoding: .utf8)!)
```

```py
response = api_request(
    "/plugins/oauth/connect/",
    method="POST",
    json_body={"plugin": "google_drive"},
)
print(response.json())
```

### GET `/plugins/oauth/callback/<plugin_key>/`

- **Status:** Active
- **Purpose:** OAuth callback endpoint that exchanges the provider code for tokens, stores a pending OAuth result, and redirects the user back to the app with a completion token.
- **Auth:** Public. The user is identified through the consumed server-side OAuth state record referenced by the signed `state` nonce.
- **Path params:**
  - `plugin_key` (`string`, required). Examples: `gmail`, `google_calendar`, `google_drive`, `google_contacts`, `outlook`, `outlook_calendar`.
- **Query params:**
  - `code` (`string`, usually required on success)
  - `state` (`string`, usually required on success)
  - `error` (`string`, optional provider error)
- **Body:** None.
- **Returns:**
  - `302` redirect on both success and failure paths.
- **Errors / notable statuses:**
  - Missing `code`/`state` or a provider `error` redirects to the failure target (default `aiva://oauth/{plugin}/failure`, resolved with the callback plugin key).
  - Invalid, expired, replayed, or plugin-mismatched state redirects to the failure target.
- **Notes / quirks:**
  - This is not a JSON endpoint.
  - OAuth state is one-time: successful callback consumes the matching `PluginOAuthStates` row, and replaying the same provider redirect fails.
  - On success, the backend stores encrypted pending token data on `PluginOAuthStates`, appends `completion_token=<opaque-token>` to the success redirect, and redirects to the success target (default `aiva://oauth/{plugin}/success`, resolved with the callback plugin key).
  - The app must finish the connect flow by calling `POST /plugins/oauth/finalize/` while authenticated as the initiating Aiva user. Credentials are not saved during the public provider callback.
  - The backend derives `account_id` for `gmail` from the Gmail profile endpoint, for `google_drive` from the Drive About API `user.emailAddress`, for `google_contacts` from Google userinfo `email`, and for Outlook plugins from Microsoft Graph `/me` `userPrincipalName`.
  - Credential persistence happens during finalize and uses `update_or_create(user, plugin, account_id, ...)`, so repeated finalized connects for the same account update the existing row.
  - `PUBLIC_BACKEND_URL` still controls the provider-facing backend callback URL. The app-return deep link is controlled separately by `PLUGIN_OAUTH_SUCCESS_REDIRECT` and `PLUGIN_OAUTH_FAILURE_REDIRECT`.
  - Static redirect overrides are supported, but plugin-aware values should include `{plugin}` so each integration can return to its own app route.
  - Google should still be configured with the backend callback URL, not `aiva://...`.
  - `google_drive` requires the Google Drive API to be enabled in Google Cloud.
  - Your app should usually open the provider `auth_url` from `/plugins/oauth/connect/` rather than calling this route directly.
- **Examples:**

```ts
const res = await fetch(
  "http://localhost:8000/plugins/oauth/callback/google_drive/?code=<oauth-code>&state=<signed-state>",
  { redirect: "manual" }
);
console.log(res.status, res.headers.get("location"));
```

```swift
let url = URL(string: "http://localhost:8000/plugins/oauth/callback/google_drive/?code=<oauth-code>&state=<signed-state>")!
let (data, response) = try await URLSession.shared.data(from: url)
print((response as? HTTPURLResponse)?.statusCode ?? -1)
print(String(data: data, encoding: .utf8) ?? "")
```

```py
response = requests.get(
    "http://localhost:8000/plugins/oauth/callback/google_drive/",
    params={"code": "<oauth-code>", "state": "<signed-state>"},
    allow_redirects=False,
)
print(response.status_code, response.headers.get("Location"))
```

### POST `/plugins/oauth/finalize/`

- **Status:** Active
- **Purpose:** Authenticated app-side completion step for OAuth. Commits a pending provider callback result into `PluginCredentials`.
- **Auth:** Bearer token required. The authenticated user must match the user that started `/plugins/oauth/connect/`.
- **Path params:** None.
- **Query params:** None.
- **Body:**
  - `plugin` (`string`, required). Plugin key such as `gmail`, `google_calendar`, `google_drive`, `google_contacts`, `outlook`, or `outlook_calendar`.
  - `completion_token` (`string`, required). Opaque token from the success deep link query string.
- **Returns:** `200` with `{"detail":"Connected","credential":{...}}`, where `credential` is a redacted [`Credential read object`](#credential-read-object).
- **Errors / notable statuses:**
  - `400` with `{"detail":"Unknown plugin"}` when the plugin key is invalid.
  - `400` with `{"detail":"Invalid OAuth completion token"}` for missing, replayed, or unknown completion tokens.
  - `400` when the pending OAuth result is expired, already finalized, or missing token data.
  - `403` when the completion token belongs to a different Aiva user.
- **Notes / quirks:**
  - This endpoint is the app/browser binding step. A provider callback alone cannot create credentials.
  - After successful finalize, pending access/refresh tokens are cleared from `PluginOAuthStates`; the completion token cannot be reused.
- **Examples:**

```ts
await apiJson("/plugins/oauth/finalize/", {
  method: "POST",
  body: JSON.stringify({
    plugin: "gmail",
    completion_token: completionTokenFromDeepLink,
  }),
});
```

### GET `/plugins/credentials/`

- **Status:** Active
- **Purpose:** List credentials owned by the authenticated user.
- **Auth:** Bearer token required.
- **Path params:** None.
- **Query params:** None.
- **Body:** None.
- **Returns:** `200` with an array of redacted [`Credential read object`](#credential-read-object) items.
- **Errors / notable statuses:**
  - `403` DRF auth failure.
- **Notes / quirks:**
  - `access_token` and `refresh_token` are intentionally not returned.
- **Examples:**

```ts
const credentials = await apiJson<Array<Record<string, unknown>>>("/plugins/credentials/");
console.log(credentials);
```

```swift
let (data, _) = try await API.request(path: "/plugins/credentials/")
print(String(data: data, encoding: .utf8)!)
```

```py
response = api_request("/plugins/credentials/")
print(response.json())
```

### POST `/plugins/credentials/`

- **Status:** Active
- **Purpose:** Manually create a credential row for the authenticated user.
- **Auth:** Bearer token required.
- **Path params:** None.
- **Query params:** None.
- **Body:**
  - `plugin` (`string`, required)
  - `account_id` (`string`, optional)
  - `access_token` (`string`, required)
  - `refresh_token` (`string`, optional)
  - `scopes` (`array`, optional)
  - `metadata` (`object`, optional)
  - `expires_at` (`ISO-8601 datetime`, optional)
  - `status` (`string`, optional; default model value is `"active"`)
- **Returns:** `201` with a redacted [`Credential read object`](#credential-read-object).
- **Errors / notable statuses:**
  - `403` DRF auth failure.
  - Validation errors return DRF serializer `400` responses.
- **Notes / quirks:**
  - Token fields are accepted on write but not returned on read.
  - `user` is automatically set from the current authenticated user.
- **Examples:**

```ts
const credential = await apiJson<Record<string, unknown>>("/plugins/credentials/", {
  method: "POST",
  body: JSON.stringify({
    plugin: "gmail",
    account_id: "user@example.com",
    access_token: "<provider-access-token>",
    refresh_token: "<provider-refresh-token>",
    scopes: ["https://www.googleapis.com/auth/gmail.readonly"],
    status: "active",
  }),
});

console.log(credential);
```

```swift
let body = try JSONSerialization.data(withJSONObject: [
    "plugin": "gmail",
    "account_id": "user@example.com",
    "access_token": "<provider-access-token>",
    "refresh_token": "<provider-refresh-token>",
    "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
    "status": "active"
])
let (data, _) = try await API.request(path: "/plugins/credentials/", method: "POST", body: body)
print(String(data: data, encoding: .utf8)!)
```

```py
response = api_request(
    "/plugins/credentials/",
    method="POST",
    json_body={
        "plugin": "gmail",
        "account_id": "user@example.com",
        "access_token": "<provider-access-token>",
        "refresh_token": "<provider-refresh-token>",
        "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
        "status": "active",
    },
)
print(response.json())
```

### GET `/plugins/credentials/<credentialId>/`

- **Status:** Active
- **Purpose:** Retrieve one credential row owned by the authenticated user.
- **Auth:** Bearer token required.
- **Path params:**
  - `credentialId` (`integer`, required)
- **Query params:** None.
- **Body:** None.
- **Returns:** `200` with a redacted [`Credential read object`](#credential-read-object).
- **Errors / notable statuses:**
  - `403` DRF auth failure.
  - `404` when the credential is not found or not owned by the user.
- **Notes / quirks:**
  - Tokens remain redacted on read.
- **Examples:**

```ts
const credential = await apiJson<Record<string, unknown>>("/plugins/credentials/4/");
console.log(credential);
```

```swift
let (data, _) = try await API.request(path: "/plugins/credentials/4/")
print(String(data: data, encoding: .utf8)!)
```

```py
response = api_request("/plugins/credentials/4/")
print(response.json())
```

### PUT `/plugins/credentials/<credentialId>/`

- **Status:** Active
- **Purpose:** Replace or partially overwrite credential fields using the manual credential write serializer.
- **Auth:** Bearer token required.
- **Path params:**
  - `credentialId` (`integer`, required)
- **Query params:** None.
- **Body:** Any subset accepted by `POST /plugins/credentials/`.
- **Returns:** `200` with a redacted [`Credential read object`](#credential-read-object).
- **Errors / notable statuses:**
  - `403` DRF auth failure.
  - `404` when the credential is not found or not owned by the user.
  - Validation errors return DRF serializer `400` responses.
- **Notes / quirks:**
  - Although this is `PUT`, the current implementation effectively supports partial overwrite semantics depending on the serializer data supplied.
- **Examples:**

```ts
const updated = await apiJson<Record<string, unknown>>("/plugins/credentials/4/", {
  method: "PUT",
  body: JSON.stringify({
    plugin: "gmail",
    account_id: "user@example.com",
    access_token: "<new-provider-access-token>",
    refresh_token: "<new-provider-refresh-token>",
    status: "active",
  }),
});

console.log(updated);
```

```swift
let body = try JSONSerialization.data(withJSONObject: [
    "plugin": "gmail",
    "account_id": "user@example.com",
    "access_token": "<new-provider-access-token>",
    "refresh_token": "<new-provider-refresh-token>",
    "status": "active"
])
let (data, _) = try await API.request(path: "/plugins/credentials/4/", method: "PUT", body: body)
print(String(data: data, encoding: .utf8)!)
```

```py
response = api_request(
    "/plugins/credentials/4/",
    method="PUT",
    json_body={
        "plugin": "gmail",
        "account_id": "user@example.com",
        "access_token": "<new-provider-access-token>",
        "refresh_token": "<new-provider-refresh-token>",
        "status": "active",
    },
)
print(response.json())
```

### PATCH `/plugins/credentials/<credentialId>/`

- **Status:** Active
- **Purpose:** Partially update a credential row.
- **Auth:** Bearer token required.
- **Path params:**
  - `credentialId` (`integer`, required)
- **Query params:** None.
- **Body:** Any subset accepted by `POST /plugins/credentials/`.
- **Returns:** `200` with a redacted [`Credential read object`](#credential-read-object).
- **Errors / notable statuses:**
  - `403` DRF auth failure.
  - `404` when the credential is not found or not owned by the user.
  - Validation errors return DRF serializer `400` responses.
- **Notes / quirks:**
  - This is the most accurate choice for partial credential updates.
- **Examples:**

```ts
const patched = await apiJson<Record<string, unknown>>("/plugins/credentials/4/", {
  method: "PATCH",
  body: JSON.stringify({
    access_token: "<new-provider-access-token>",
    status: "active",
  }),
});

console.log(patched);
```

```swift
let body = try JSONSerialization.data(withJSONObject: [
    "access_token": "<new-provider-access-token>",
    "status": "active"
])
let (data, _) = try await API.request(path: "/plugins/credentials/4/", method: "PATCH", body: body)
print(String(data: data, encoding: .utf8)!)
```

```py
response = api_request(
    "/plugins/credentials/4/",
    method="PATCH",
    json_body={"access_token": "<new-provider-access-token>", "status": "active"},
)
print(response.json())
```

### DELETE `/plugins/credentials/<credentialId>/`

- **Status:** Active
- **Purpose:** Delete a credential row.
- **Auth:** Bearer token required.
- **Path params:**
  - `credentialId` (`integer`, required)
- **Query params:** None.
- **Body:** None.
- **Returns:** `204` with an empty body.
- **Errors / notable statuses:**
  - `403` DRF auth failure.
  - `404` when the credential is not found or not owned by the user.
- **Notes / quirks:**
  - This deletes the local credential row only; it does not call provider revoke. Use `/disconnect/` for revoke-first behavior.
- **Examples:**

```ts
const res = await fetch("http://localhost:8000/plugins/credentials/4/", {
  method: "DELETE",
  headers: { Authorization: `Bearer ${accessToken}` },
});
console.log(res.status);
```

```swift
let (_, response) = try await API.request(path: "/plugins/credentials/4/", method: "DELETE", body: nil, contentType: nil)
print(response.statusCode)
```

```py
response = api_request("/plugins/credentials/4/", method="DELETE")
print(response.status_code)
```

### POST `/plugins/credentials/<credentialId>/refresh/`

- **Status:** Active
- **Purpose:** Force a credential refresh through `CredentialService`.
- **Auth:** Bearer token required.
- **Path params:**
  - `credentialId` (`integer`, required)
- **Query params:** None.
- **Body:** None.
- **Returns:**
  - `200` with `{"detail":"Refreshed"}`
- **Errors / notable statuses:**
  - `400` with `{"detail":"Refresh failed","error":"..."}` on refresh failure.
  - `403` DRF auth failure.
  - `404` with `{"detail":"Not found"}` when the credential is not owned by the user.
- **Notes / quirks:**
  - This is a JSON endpoint, unlike the OAuth callback.
- **Examples:**

```ts
const result = await apiJson<{ detail: string }>("/plugins/credentials/4/refresh/", {
  method: "POST",
});

console.log(result.detail);
```

```swift
let (data, _) = try await API.request(path: "/plugins/credentials/4/refresh/", method: "POST", body: nil, contentType: nil)
print(String(data: data, encoding: .utf8)!)
```

```py
response = api_request("/plugins/credentials/4/refresh/", method="POST")
print(response.json())
```

### POST `/plugins/credentials/<credentialId>/disconnect/`

- **Status:** Active
- **Purpose:** Attempt provider revoke, then delete the local credential row.
- **Auth:** Bearer token required.
- **Path params:**
  - `credentialId` (`integer`, required)
- **Query params:** None.
- **Body:** None.
- **Returns:** `204` with an empty body.
- **Errors / notable statuses:**
  - `403` DRF auth failure.
  - `404` with `{"detail":"Not found"}` when the credential is not owned by the user.
- **Notes / quirks:**
  - The backend logs revoke failures but still deletes the local row.
- **Examples:**

```ts
const res = await fetch("http://localhost:8000/plugins/credentials/4/disconnect/", {
  method: "POST",
  headers: { Authorization: `Bearer ${accessToken}` },
});
console.log(res.status);
```

```swift
let (_, response) = try await API.request(path: "/plugins/credentials/4/disconnect/", method: "POST", body: nil, contentType: nil)
print(response.statusCode)
```

```py
response = api_request("/plugins/credentials/4/disconnect/", method="POST")
print(response.status_code)
```

## Non-active / legacy endpoint families

### Legacy MCP endpoint family (`/mcp-client/`, MCP server/plugin runtime paths)

- **Status:** Non-active
- **Historical path family:** `/mcp-client/` and related MCP runtime surfaces.
- **Current behavior:** Not part of the live Django URL tree. Requests to these paths are not supported by the current backend application.
- **Why non-active:** [`backend/urls.py`](./backend/urls.py) does not include any MCP route tree. Only legacy directories remain under:
  - [`mcp_client/`](./mcp_client)
  - [`mcp_server/`](./mcp_server)
  - [`mcp_integration/`](./mcp_integration)
- **What replaced it:** `POST /agent/` is the live planner/orchestrator entrypoint.
- **Notes / quirks:**
  - Do not build new clients against `/mcp-client/`.
  - The legacy MCP directories are orientation artifacts, not active HTTP surfaces.

### Backend-owned login/signup API

- **Status:** Non-active / not implemented
- **Historical or assumed paths:** Examples might include `/login/`, `/signup/`, or `/auth/login/`, but none are routed by the live backend.
- **Current behavior:** No backend login/signup endpoint exists.
- **Why non-active:** Authentication is externalized to Supabase. This backend only verifies the Supabase access token on incoming API requests.
- **What replaced it:** Supabase Auth plus `Authorization: Bearer <Supabase access token>` on live backend endpoints.
- **Notes / quirks:**
  - The backend mirrors users locally by `supabase_uid` when they first authenticate successfully.
  - If you need a login flow, call Supabase Auth first, then use the returned access token with this backend.
