# Configuration

All configuration comes from environment variables, read in `backend/settings.py` via `django-environ`. A `.env` file in the project root is loaded automatically. [`.env.example`](../.env.example) lists every variable.

**Required** means Django will not start without it. **Required to use** means startup works, but the feature fails at runtime without it.

## Django

| Variable | Required | Default | Notes |
|---|---|---|---|
| `SECRET_KEY` | yes | — | Long random string. |
| `DEBUG` | no | `False` | Never `True` outside local development. |
| `ALLOWED_HOSTS` | yes when `DEBUG=False` | `localhost,127.0.0.1` if `DEBUG` | Comma-separated. |
| `CSRF_TRUSTED_ORIGINS` | no | empty | Comma-separated origins. |
| `CORS_ALLOWED_ORIGINS` | no | `localhost:3000,5173` when `DEBUG`, else empty | Comma-separated origins. |
| `PUBLIC_BACKEND_URL` | no | empty | Base URL that OAuth providers redirect back to. If empty, it is derived from the request. |

## PostgreSQL

PostgreSQL is required. Some constraints (`NULLS NOT DISTINCT`) and row locking (`SKIP LOCKED`) are Postgres-specific.

| Variable | Required | Default |
|---|---|---|
| `POSTGRES_HOST` | yes | — |
| `POSTGRES_PORT` | no | `5432` |
| `POSTGRES_DB` | yes | — |
| `POSTGRES_USER` | yes | — |
| `SUPABASE_DB_PW` | yes | — (the database password; the name is inherited) |
| `POSTGRES_SSLMODE` | no | `require`; use `disable` for a local container |

## Authentication

API requests are authenticated with Supabase-issued HS256 JWTs (`Authorization: Bearer <token>`). A local user is created automatically for each new token subject. Single-owner Django authentication is planned to replace this (see the [roadmap](roadmap.md)).

| Variable | Required | Default |
|---|---|---|
| `SUPABASE_URL` | yes | — (issuer is `<SUPABASE_URL>/auth/v1`) |
| `SUPABASE_JWT_SECRET` | yes | — |
| `SUPABASE_JWT_AUDIENCE` | no | `authenticated` |

## Redis and Celery

| Variable | Required | Default | Notes |
|---|---|---|---|
| `REDIS_URL` | no | empty | When set, it is used as the Django cache. Without it, each process uses an in-memory cache: pending plans and throttle counters are not shared and do not survive restarts. |
| `CELERY_BROKER_URL` | no | `REDIS_URL`, then `redis://localhost:6379/0` | |
| `CELERY_TASK_ALWAYS_EAGER` | no | `False` | Runs tasks inline (useful in tests). |

Scheduled workflow runs need a Celery worker *and* a single Celery beat process. Beat enqueues due runs every 60 seconds.

## Credential encryption

OAuth tokens are encrypted at rest with Fernet.

| Variable | Required | Default | Notes |
|---|---|---|---|
| `CREDENTIAL_ENCRYPTION_KEY` | required to use integrations | empty | Generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. |
| `CREDENTIAL_ENCRYPTION_KEYS` | no | empty | Comma-separated keys, newest first, for rotation. Overrides the single key. |
| `CREDENTIAL_ENCRYPTION_ALLOW_PLAINTEXT_FALLBACK` | no | `False` | Migration-only escape hatch for legacy plaintext rows. |

## LLM

| Variable | Required | Default |
|---|---|---|
| `OPENAI_KEY` | yes | — |
| `PLANNER_MODEL` | no | `gpt-4o-mini` |
| `PROCESSING_LLM_MODEL` | no | `gpt-4o-mini` |

## Integrations (OAuth clients)

| Variable | Required | Used by |
|---|---|---|
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | yes (settings require them) | Gmail, Google Calendar, Google Contacts, Google Drive |
| `MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET` | required to use | Outlook Mail, Outlook Calendar |
| `NOTION_CLIENT_ID`, `NOTION_CLIENT_SECRET` | required to use | Notion |
| `PLUGIN_OAUTH_SUCCESS_REDIRECT`, `PLUGIN_OAUTH_FAILURE_REDIRECT` | no | Where the callback sends the browser. `{plugin}` is substituted. Defaults to the `aiva://` mobile deep link. |

Provider callback URLs to register: `<PUBLIC_BACKEND_URL>/plugins/oauth/callback/<plugin>/`, where `<plugin>` is one of `gmail`, `google_calendar`, `google_contacts`, `google_drive`, `outlook`, `outlook_calendar`, `notion`.

## Built-in tool API keys

These are read directly from the environment when the tool runs.

| Variable | Used by |
|---|---|
| `OPENWEATHER_API_KEY` | `weather.*` |
| `TAVILY_API_KEY` | `web.search` |

## Tuning

| Variable | Default | Effect |
|---|---|---|
| `PLANNER_TIMEOUT` | `60` | Seconds per planner/intent LLM call. |
| `PROCESSING_LLM_TIMEOUT` | `60` | Seconds per `processing_llm` call. |
| `PROCESSING_LLM_MAX_TOKENS` | `1024` | Output token cap for `processing_llm`. |
| `TOOL_STEP_TIMEOUT` | `60` | Seconds per plan step, including retries. |
| `PLAN_CACHE_TTL` | `3600` | Seconds to cache plans for history-free prompts. `0` disables caching. Caching can serve a stale plan for time-relative requests ("today", "tomorrow"). |
| `AGENT_THROTTLE_RATE` | `20/min` | Per-user rate limit on `/agent/` and `/agent/stream/`. |
| `AGENT_MAX_MODIFY_REVISIONS` | `5` | Plan revisions allowed before a pending plan is discarded. |
| `PLANNER_USAGE_RETENTION_DAYS` | `90` | Default window for `manage.py purge_planner_usage`. |
