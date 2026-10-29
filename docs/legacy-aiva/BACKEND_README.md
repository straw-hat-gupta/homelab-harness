# Aiva Backend

Django REST API powering the Aiva AI assistant. Accepts natural-language prompts, produces multi-step execution plans via an LLM, and executes them using a registry of tools.

---

## Quick start

```bash
cp .env.example .env        # fill in secrets (see Env vars below)
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Or with Docker Compose (see `docs/DOCKERIZE_BACKEND.md`):

```bash
docker compose up
```

---

## Architecture

```
POST /agent/  →  run_prompt()  →  plan()  →  execute()  →  tool fns
                                  ↑
                           planner (OpenAI)
```

1. **Planner** (`planner/`) — translates a prompt + conversation history + user memories into a typed JSON plan (`Plan` with `PlanStep[]`).
2. **Orchestrator** (`orchestrator/`) — executes each step in order, injects credentials for OAuth tools, resolves `$variable` references between steps.
3. **Tool registry** (`tools/registry.py`) — all tools self-register on import via `register(ToolDef(...))`. Auto-discovery runs from the `tools` Django app config in `tools/apps.py`.
4. **Agent view** (`agent/views.py`) — handles confirmation flow (pending plans), capabilities shortcut, rate limiting, SSE streaming, and error translation.

---

## Tools

### Always available (no plugin connection required)

| Tool | Description |
|---|---|
| `processing_llm` | Direct LLM response — greetings, explanations, error messages |
| `weather.get_current_weather` | Current weather by city |
| `weather.get_weather_forecast` | Multi-day forecast |
| `weather.get_weather_by_coordinates` | Weather by lat/lon |
| `contacts.search` | Search contacts by name/email |
| `contacts.create` | Create a contact |
| `contacts.update` | Update a contact |
| `contacts.delete` | Delete a contact |
| `web.search` | Web search via Tavily (returns ranked results + optional AI answer) |
| `memory.save` | Persist a key/value memory about the user |
| `memory.delete` | Delete a saved memory by key |

### Gmail (requires OAuth connection)

`gmail.search_emails`, `gmail.get_unread_emails`, `gmail.get_sent_emails`, `gmail.get_starred_emails`, `gmail.get_label_emails`, `gmail.get_next_page`, `gmail.get_drafts`, `gmail.send_email` ✱, `gmail.send_draft` ✱, `gmail.get_attachment`, `gmail.trash_email` ✱, `gmail.mark_read`, `gmail.mark_unread`, `gmail.add_label`, `gmail.remove_label`, `gmail.create_draft`

### Google Calendar (requires OAuth connection)

`calendar.list_calendars`, `calendar.list_events`, `calendar.create_event`, `calendar.update_event`, `calendar.delete_event` ✱

### Google Drive (requires OAuth connection)

`drive.list_files`, `drive.search_files`, `drive.get_file_metadata`

✱ = requires user confirmation before execution

---

## Key endpoints

**Agent** (conversational interface)

| Method | Path | Description |
|---|---|---|
| `POST` | `/agent/` | Run a prompt (sync) |
| `POST` | `/agent/stream/` | Run a prompt (SSE streaming) |
| `GET` | `/agent/actions/` | Audit log of confirmed actions |
| `DELETE` | `/agent/reset/<project_id>/` | Clear conversation + pending plan |
| `GET/POST` | `/agent/memory/` | List or upsert user memories |
| `PUT/DELETE` | `/agent/memory/<id>/` | Update or delete a memory |

**Platform** (tools and workflows — consumed by agent, workflow builder, and future features)

| Method | Path | Description |
|---|---|---|
| `GET` | `/tools/` | All tool schemas; `?plugin=<id>` to filter by plugin |
| `GET/POST` | `/workflows/` | List or create saved workflows |
| `GET/PUT/DELETE` | `/workflows/<id>/` | Read/update/delete a workflow |
| `POST` | `/workflows/<id>/run/` | Execute a saved workflow directly |
| `GET/POST` | `/scheduled-runs/` | List or create scheduled workflow runs |
| `GET/PUT/DELETE` | `/scheduled-runs/<id>/` | Read/update/delete a scheduled run |
| `POST` | `/scheduled-runs/<id>/run-now/` | Queue one immediate scheduled-run execution |
| `GET` | `/scheduled-runs/<id>/executions/` | List scheduled-run execution history |

**Plugins, Projects, Contacts**

| Method | Path | Description |
|---|---|---|
| `GET/POST` | `/projects/` | List or create projects |
| `GET/PUT/DELETE` | `/projects/<id>/` | Read/update/delete a project |
| `POST` | `/plugins/oauth/connect/` | Start plugin OAuth flow |
| `GET` | `/plugins/oauth/callback/<plugin>/` | OAuth callback |
| `GET` | `/plugins/credentials/` | List connected credentials |
| `POST` | `/plugins/credentials/<id>/disconnect/` | Revoke + delete credential |
| `GET/POST` | `/contacts/` | Contacts CRUD |
| `GET/POST/PUT/DELETE` | `/project-context/` | Conversation transcript |

Full reference: `docs/ENDPOINTS.md`

---

## Persistent memory

User memories are key/value pairs stored in `UserMemory` (DB) and injected into every planner call. The planner uses them as ground truth (e.g. pre-filling a city for weather without asking). Tools `memory.save` and `memory.delete` let the agent update memories during a session.

REST: `GET/POST /agent/memory/`, `PUT/DELETE /agent/memory/<id>/`

---

## Env vars

```
SECRET_KEY=
DEBUG=False
ALLOWED_HOSTS=localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=http://localhost:8000
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173
REDIS_URL=                     # optional; Docker Compose defaults to redis://redis:6379/0
CELERY_BROKER_URL=             # optional; defaults to REDIS_URL, then redis://localhost:6379/0

SUPABASE_URL=
SUPABASE_DB_PW=
SUPABASE_JWT_SECRET=
SUPABASE_JWT_AUDIENCE=authenticated

POSTGRES_HOST=
POSTGRES_DB=postgres
POSTGRES_USER=postgres
POSTGRES_PORT=5432
POSTGRES_SSLMODE=require

PUBLIC_BACKEND_URL=http://localhost:8000
OPENAI_KEY=
OPENWEATHER_API_KEY=
TAVILY_API_KEY=
PLANNER_MODEL=gpt-4o-mini
PROCESSING_LLM_MODEL=gpt-4o-mini
PLANNER_TIMEOUT=60

GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
MICROSOFT_CLIENT_ID=          # optional; required for Outlook Mail / Outlook Calendar plugins
MICROSOFT_CLIENT_SECRET=      # optional; required for Outlook Mail / Outlook Calendar plugins
PLUGIN_OAUTH_SUCCESS_REDIRECT=aiva://oauth/{plugin}/success
PLUGIN_OAUTH_FAILURE_REDIRECT=aiva://oauth/{plugin}/failure

CREDENTIAL_ENCRYPTION_KEY=   # generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
CREDENTIAL_ENCRYPTION_KEYS=  # optional comma-separated rotation keys, newest first
CREDENTIAL_ENCRYPTION_ALLOW_PLAINTEXT_FALLBACK=False  # migration-only escape hatch
```

Optional tuning:

```
CELERY_TASK_ALWAYS_EAGER=False
PLAN_CACHE_TTL=3600           # seconds; 0 = disable plan caching
AGENT_THROTTLE_RATE=20/min
AGENT_MAX_MODIFY_REVISIONS=5
PLANNER_USAGE_RETENTION_DAYS=90
```

Scheduled runs require Redis plus Celery worker and Beat processes. The Docker Compose files include these services for local development and image-only runner mode.

---

## Docs

| File | Contents |
|---|---|
| `docs/FEATURES.md` | Full feature descriptions and implementation details |
| `docs/CHANGELOG.md` | Change history |
| `docs/ENDPOINTS.md` | Endpoint reference with examples |
| `docs/SETUP.md` | Detailed setup guide |
| `docs/DOCKERIZE_BACKEND.md` | Docker Compose deployment |
| `docs/ADDING_OAUTH_PLUGIN.md` | How to add a new OAuth plugin |
| `docs/TODO.md` | Backlog and known gaps |

---

## Running tests

```bash
python manage.py test --keepdb
```
