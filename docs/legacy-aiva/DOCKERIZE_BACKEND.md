# Dockerize `v2/backend`

This guide is about the backend in this repository as it exists today. It is not a generic Django Docker tutorial.

The goal is to teach you how to package `v2/backend` so the backend runs the same way on different machines without changing the backend architecture.

## What This Backend Actually Is

Before writing Docker files, anchor on the real runtime:

- [`start_server.py`](./start_server.py) starts `uvicorn backend.asgi:application --reload`. That is a local development launcher, not the best default container command.
- [`manage.py`](./manage.py) is the Django admin and migration entrypoint.
- [`backend/settings.py`](./backend/settings.py) reads required env vars from [`.env.example`](./.env.example).
- The backend stores conversation history and pending plans in the database (no file-backed runtime state directories required).
- The live HTTP surface is the Django backend documented in [`ENDPOINTS.md`](./ENDPOINTS.md).
- The current Compose files are `docker-compose.yml` (base, prod-like web/worker/beat/Redis stack), `docker-compose.dev.yml` (dev overlay with bind mount and web `--reload`), and `compose.image.yaml` (image-only runner for frontend developers).

Also note what is not the live runtime path:

- The legacy `mcp_client/`, `mcp_integration/`, and `mcp_server/` directories exist in the repo, but they are not part of the live Django URL tree in [`backend/urls.py`](./backend/urls.py).
- Do not let those directories drive your Docker design for the current backend service.

## Container Boundary for This Repo

For this repo, the clean container boundary is:

- one web container for the Django backend API
- one Celery worker container for scheduled workflow execution
- one Celery Beat container for due-schedule dispatch
- one Redis broker container for local/dev scheduled-run queues
- external Supabase Auth
- external Postgres
- external OpenAI
- external provider APIs such as Google, Microsoft Graph, OpenWeatherMap, and Tavily

That is the right shape because the backend already expects external settings like:

- `POSTGRES_HOST`
- `SUPABASE_URL`
- `SUPABASE_JWT_SECRET`
- `OPENAI_KEY`
- `OPENWEATHER_API_KEY`
- `TAVILY_API_KEY`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- optional `MICROSOFT_CLIENT_ID`
- optional `MICROSOFT_CLIENT_SECRET`
- optional `REDIS_URL`
- optional `CELERY_BROKER_URL`
- `PUBLIC_BACKEND_URL`
- optional `PLUGIN_OAUTH_SUCCESS_REDIRECT`
- optional `PLUGIN_OAUTH_FAILURE_REDIRECT`

Do not add a local Postgres service to the primary example just because Docker Compose makes it easy. That would teach the wrong runtime boundary for this repo.

This backend is stateless from a filesystem perspective. Conversation history, pending plans, credentials, saved workflows, scheduled runs, scheduled execution history, tasks, and memories are stored in the database via Django models. Redis is runtime infrastructure for cache/broker data, not the source of record. No file-backed runtime state directories are needed, and no Docker volumes are required for backend application state persistence.

## Docker Basics in the Context of This Repo

### Image vs container

- An image is the packaged filesystem and startup definition.
- A container is a running instance of that image.

For this repo:

- the image should contain Python, dependencies, app code, and a startup command
- the container should receive secrets and connection settings at runtime through `.env`

### Dockerfile vs Compose

- A `Dockerfile` explains how to build the image.
- `docker compose` explains how to run one or more containers consistently.

For this repo:

- learn `docker build` and `docker run` first so you understand the moving parts
- then use Compose to avoid retyping the same flags

### Layers and build cache

Docker builds in layers. If an early layer changes, later layers rebuild too.

That is why you should copy [`requirements.txt`](./requirements.txt) before copying the full source tree:

- dependency layer changes rarely
- application code changes often
- this keeps rebuilds faster

### Bind mounts vs named volumes

- A bind mount maps a host path directly into the container.
- A named volume is managed by Docker.

For this repo today:

- the committed setup uses neither bind mounts nor named volumes for application state
- conversation history and pending plans are stored in the database, not the container filesystem
- state persists across container recreation as long as the database connection is stable

If you later add mounts:

- bind mounts are useful when you want to inspect files directly from the host
- named volumes are useful when you want Docker-managed persistence
- mount targets inside the container must be absolute paths, even when the backend config itself uses relative paths

### ENTRYPOINT vs CMD

- `ENTRYPOINT` defines the main executable wrapper
- `CMD` provides default arguments or the default process

A good pattern for this backend is:

- `ENTRYPOINT` runs a small shell script
- the shell script runs migrations
- `CMD` starts `uvicorn`

### Port publishing

`-p 8000:8000` means:

- left side: host port
- right side: container port

This backend listens on port `8000`, so you publish that port from the container to the host.

## 1. Read the Backend Before Writing Docker

The fastest way to write the wrong Docker setup is to skip the code and guess.

Run these from [`v2/backend`](./):

```bash
cd v2/backend
sed -n '1,200p' start_server.py
sed -n '1,200p' manage.py
sed -n '1,260p' backend/settings.py
sed -n '1,220p' .env.example
sed -n '1,220p' requirements.txt
```

What those files tell you:

- `start_server.py` proves the live server is `uvicorn backend.asgi:application`
- `manage.py` proves you will need Django management commands in the container
- `backend/settings.py` proves the backend requires a real env contract at startup
- `.env.example` tells you exactly which env vars the container must receive
- `requirements.txt` tells you what Python runtime and dependency footprint the image needs

## 2. Design the Image for This Backend

The image for this backend should:

- build from [`requirements.txt`](./requirements.txt)
- use the current `v2/backend` directory as the build context
- run from `v2/backend` inside the container
- expose port `8000`
- start `uvicorn backend.asgi:application --host 0.0.0.0 --port 8000`
- avoid `--reload` in the normal container run
- run as a non-root user

### Why avoid `--reload`

`--reload` is useful in local source-mounted development because it watches files and restarts the process.

For a portable container:

- it starts extra watcher processes
- it is noisier and less predictable
- it is not the normal production-ish runtime pattern

Use plain `uvicorn` in the image. If you later want a separate dev-only Docker setup, add that intentionally.

### Why Python `3.13-slim`

This repo is currently being run locally on Python `3.13.x`, so `python:3.13-slim` is the closest simple base image.

That choice also lines up with the current dependency set:

- `psycopg2-binary` usually avoids compiling PostgreSQL bindings from source
- Pillow commonly has wheels for mainstream platforms
- the Google and OpenAI clients are Python libraries, not separate services

If you later hit a wheel/build issue on a different CPU architecture, that is when you add OS build packages. Do not add them preemptively without a concrete failure.

## 3. Write the Support Files

This section shows the concrete support files for this backend. Keep the committed versions in sync with the examples and explanations below.

### `.dockerignore`

Create a `.dockerignore` next to [`requirements.txt`](./requirements.txt):

```dockerignore
.git
.gitignore
.venv
.env
.env.*
__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.DS_Store
dist/
build/
*.log
mcp_client/
mcp_integration/
mcp_server/
```

Why each part exists:

- `.venv`, `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`: local Python junk should not bloat the build context
- `.env` and `.env.*`: secrets belong at runtime, not inside the image
- `dist/`, `build/`, `*.log`, `.DS_Store`: normal local output noise
- `mcp_client/`, `mcp_integration/`, `mcp_server/`: legacy repo areas that are not part of the live Django runtime path today

The last point is repo-specific. If those legacy directories ever become part of the live service again, remove those ignore rules.

### `Dockerfile`

Create a `Dockerfile` in [`v2/backend`](./):

```dockerfile
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /backend_app

COPY requirements.txt requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

RUN useradd --create-home --shell /bin/sh appuser \
    && chmod +x entrypoint.sh \
    && chown -R appuser:appuser /backend_app

USER appuser

EXPOSE 8000

ENTRYPOINT ["/backend_app/entrypoint.sh"]
CMD ["uvicorn", "backend.asgi:application", "--host", "0.0.0.0", "--port", "8000"]
```

Why each instruction exists:

- `FROM python:3.13-slim`
  - starts from a small Python base that matches the repo's current major/minor runtime
- `ENV PYTHONDONTWRITEBYTECODE=1`
  - avoids writing `.pyc` files into the container filesystem
- `ENV PYTHONUNBUFFERED=1`
  - makes logs flush immediately so `docker logs` is useful
- `ENV PIP_NO_CACHE_DIR=1`
  - avoids storing pip download cache in the image
- `WORKDIR /backend_app`
  - sets a stable application working directory inside the container
- `COPY requirements.txt requirements.txt`
  - copies only dependencies first so Docker can reuse the pip-install layer when code changes
- `RUN pip install ...`
  - installs backend dependencies once per dependency change
- `COPY . .`
  - copies the actual backend source after dependencies are installed
- `RUN useradd ...`
  - creates a non-root runtime user
- `chmod +x entrypoint.sh`
  - makes the startup script executable
- `chown -R appuser:appuser /backend_app`
  - ensures the non-root user can read the app and write runtime state
- `USER appuser`
  - drops root privileges before runtime
- `EXPOSE 8000`
  - documents the intended application port
- `ENTRYPOINT`
  - always runs the startup script first
- `CMD`
  - provides the default app server command

### `entrypoint.sh`

Create `entrypoint.sh` in [`v2/backend`](./):

```sh
#!/bin/sh
set -eu

python manage.py migrate

exec "$@"
```

Why this pattern is clean:

- `set -eu`
  - fail on unset variables and command errors
- `python manage.py migrate`
  - aligns the database schema before serving requests
- `exec "$@"`
  - replaces the shell process with `uvicorn`
  - this matters because the main server should receive signals directly for clean shutdown

Without `exec`, the shell stays as PID 1 and signal handling becomes messier.

### `docker-compose.yml` and `docker-compose.dev.yml`

The repo ships two Compose files:

**`docker-compose.yml`** — base, prod-like:

```yaml
services:
  backend:
    build: .
    env_file: .env
    ports:
      - "8000:8000"
    restart: unless-stopped
```

**`docker-compose.dev.yml`** — dev overlay, applied on top:

```yaml
services:
  backend:
    volumes:
      - .:/backend_app
    command: ["uvicorn", "backend.asgi:application", "--host", "0.0.0.0", "--port", "8000", "--reload"]
    environment:
      - DEBUG=True
```

Why this split is clean:

- `docker-compose.yml` alone runs a frozen image build — good for prod-like local testing
- `docker-compose.dev.yml` adds a bind mount and `--reload` so code changes reflect immediately without rebuilding
- no `volumes` block for state because conversation history and pending plans are DB-backed

For dev, apply both files:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

For prod-like local testing, use only the base:

```bash
docker compose -f docker-compose.yml up --build
```

Why there is no Postgres service here:

- this backend is already designed around external Postgres settings
- adding a local DB service in the primary example would teach the wrong default architecture

## 4. Run with Raw Docker Commands

Learn this path first. If you understand `docker build` and `docker run`, Compose becomes obvious instead of magical.

### Build the image

From [`v2/backend`](./):

```bash
cd v2/backend
docker build -t aiva-backend:local .
```

What that means:

- `docker build`
  - build an image from the current directory
- `-t aiva-backend:local`
  - tag the resulting image so you can run it by name later
- `.`
  - use the current directory as the build context

### Run the container

```bash
docker run --name aiva-backend \
  --env-file .env \
  -p 8000:8000 \
  aiva-backend:local
```

What each flag does:

- `--name aiva-backend`
  - gives the container a stable name for `docker logs`, `docker stop`, and `docker exec`
- `--env-file .env`
  - passes the backend's required env vars into the container at runtime
- `-p 8000:8000`
  - publishes container port `8000` to host port `8000`
- `aiva-backend:local`
  - the image to run

### Useful raw Docker debug commands

```bash
docker logs -f aiva-backend
docker exec -it aiva-backend sh
docker inspect aiva-backend
```

Why these matter:

- `docker logs -f` is your first stop for Django startup failures
- `docker exec -it ... sh` lets you inspect the live container
- `docker inspect` shows the final env, ports, and mounts

## 5. Run with Compose for Repeatability

Once the raw commands make sense, use Compose so your normal workflow is one command instead of a long flag list.

From [`v2/backend`](./):

```bash
cd v2/backend
docker compose -f docker-compose.yml up --build
```

Why this is easier day to day:

- `--build` rebuilds if the image definition changed
- Compose remembers ports and env files
- `docker compose -f docker-compose.yml down` stops the stack cleanly

Useful follow-up commands:

```bash
docker compose -f docker-compose.yml logs -f backend
docker compose -f docker-compose.yml exec backend sh
docker compose -f docker-compose.yml down
```

Design notes for this repo:

- keep the main app process defined in the image
- avoid duplicating the startup command in Compose unless you truly need an override
- keep the Compose file to one service until you have a strong reason to model more infrastructure locally

## 6. Verify This Repo Works in the Container

Do not stop at "the container started". Verify the actual backend behaviors that matter in this repository.

### Check migrations and startup logs

Look for successful startup in:

```bash
docker logs -f aiva-backend
```

Success should look like:

- migrations run without crashing
- `uvicorn` binds to `0.0.0.0:8000`
- no missing-env or database-connection failure at startup

### Verify authenticated API access

Use a valid Supabase access token and call a live endpoint from [`ENDPOINTS.md`](./ENDPOINTS.md):

```bash
curl -X GET "http://localhost:8000/projects/" \
  -H "Authorization: Bearer <SUPABASE_ACCESS_TOKEN>"
```

What success means here:

- auth is working inside the container
- `SUPABASE_URL` and `SUPABASE_JWT_SECRET` are correct
- the backend can complete a normal DRF request

### Verify the agent path

```bash
curl -X POST "http://localhost:8000/agent/" \
  -H "Authorization: Bearer <SUPABASE_ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"hello"}'
```

What success means here:

- the planner/orchestrator path is running inside the container
- `OPENAI_KEY` is present and usable
- the database is reachable (conversation context is stored there)

### Verify runtime-state behavior

Conversation history and pending plans are stored in the database, so they survive container restarts and recreation as long as the database connection is unchanged. After a successful `/agent/` call, stop and recreate the container — the next request on the same project should still have access to prior context.

### Verify Gmail OAuth assumptions

The callback path for this repo is:

- `/plugins/oauth/callback/gmail/`

Containerization does not change that path, but it does change what `PUBLIC_BACKEND_URL` must point to.

If you are testing Gmail OAuth:

- `PUBLIC_BACKEND_URL` must be the externally reachable origin for the running backend
- do not set it to an internal Docker hostname unless Google can actually reach that hostname

For purely local Docker testing, that often means using a tunnel or a real deployed hostname when you need the callback to work end to end.

## 7. Common Failures in This Repo

### Missing `SUPABASE_JWT_SECRET`

Symptom:

- backend starts failing auth with invalid token or signature errors

Why:

- this repo verifies Supabase bearer tokens with `HS256`
- the backend must have the real `SUPABASE_JWT_SECRET`, not the anon key

### Wrong `SUPABASE_URL`

Symptom:

- tokens that worked elsewhere fail issuer validation

Why:

- the token issuer must match the Supabase project configured in the container

### Missing `OPENAI_KEY`

Symptom:

- container fails at startup or `/agent/` fails when planner/LLM code runs

Why:

- this backend requires `OPENAI_KEY` in the env contract

### Wrong `PUBLIC_BACKEND_URL`

Symptom:

- Gmail OAuth connect starts but callback handling fails or lands on the wrong host

Why:

- the backend builds OAuth redirect URIs from `PUBLIC_BACKEND_URL`
- the value must match the externally reachable backend origin

### Database connection fails at startup

Symptom:

- migrations fail or `/agent/` returns database errors

Why:

- `POSTGRES_HOST`, `POSTGRES_DB`, `POSTGRES_USER`, `SUPABASE_DB_PW`, or `POSTGRES_PORT` is wrong
- verify these match your Supabase project settings and that the container can reach the host

### Using `start_server.py` in the main container

Symptom:

- extra reloader processes
- noisy logs
- development-style behavior in the portable runtime

Why:

- [`start_server.py`](./start_server.py) uses `--reload`
- that is the wrong default for the main backend container

Use plain `uvicorn` in the image instead.

### Looking for backend login endpoints

Symptom:

- you try to test `/login` or `/signup` inside the backend container and nothing exists

Why:

- this backend does not expose its own login/signup API
- auth is external via Supabase bearer tokens

Get the token from Supabase first, then call the backend.

## Recommended Workflow

For this repo, the clean sequence is:

1. keep [`.env.example`](./.env.example) as the source of truth for required env names
2. use the committed `Dockerfile`, `entrypoint.sh`, `.dockerignore`, `docker-compose.yml`, `docker-compose.dev.yml`, and `compose.image.yaml` files in [`v2/backend`](./)
3. build with `docker build`
4. run once with raw `docker run` until you understand the ports, env, and container-local runtime state
5. switch to Compose for repeatability
6. verify real backend flows, not just container startup

That sequence matters. If you start with a big Compose stack before you understand the backend boundary, you make debugging harder.

## Minimal File Set

The committed repo already has all required files:

1. `.dockerignore`
2. `Dockerfile`
3. `entrypoint.sh`
4. `docker-compose.yml` (base)
5. `docker-compose.dev.yml` (dev overlay)

Keep secrets in `.env`, not in the image. Verify `/projects/`, `/agent/`, and Gmail OAuth callback assumptions after first boot.
