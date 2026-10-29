# Aiva Backend Setup

This guide is split by audience:

- backend developers who have repo access and work in [`v2/backend`](/Users/samgupta/Github/Aiva/v2/backend)
- frontend developers who only need to run a prebuilt backend image locally

The backend API runs as a web container. Scheduled runs additionally require a Celery worker, Celery Beat, and Redis. The Compose files define those local services, while the backend still depends on external services:

- Supabase Auth
- Supabase/Postgres
- OpenAI
- Google OAuth plus Gmail / Google Calendar / Google Drive APIs if those plugins are used

## Shared Prerequisites

Both setup paths require:

- Docker Desktop or Docker Engine with Compose support
- access to the backend `.env` values for the target environment
- a reachable Supabase project
- a valid OpenAI API key
- Google OAuth credentials if Gmail, Google Calendar, Google Drive, or Google Contacts support is needed

Verify Docker is available:

```bash
docker version
docker compose version
```

If `docker version` shows only the client, start Docker Desktop or the Docker daemon before continuing.

## Shared Environment Setup

The backend reads configuration from `.env`.

Current env contract:

```dotenv
# Optional for image-only frontend runner mode.
AIVA_BACKEND_IMAGE=ghcr.io/arceus-aiva/aiva-backend:latest
AIVA_BACKEND_PORT=8000

SECRET_KEY=replace-with-a-real-django-secret
DEBUG=False
ALLOWED_HOSTS=localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=http://localhost:8000
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173
# Optional. Docker Compose defaults both to redis://redis:6379/0 when blank.
# Non-Docker Celery defaults to redis://localhost:6379/0 when both are blank.
REDIS_URL=
CELERY_BROKER_URL=

SUPABASE_URL=https://your-project-id.supabase.co
# Optional for manual Supabase Auth login helpers such as curl, Postman, and backend/test_login.py.
# Django runtime auth verifies bearer tokens with SUPABASE_JWT_SECRET and does not require this value.
SUPABASE_ANON_KEY=replace-with-your-supabase-anon-key
SUPABASE_DB_PW=replace-with-your-supabase-db-password
SUPABASE_JWT_SECRET=replace-with-your-supabase-jwt-secret
SUPABASE_JWT_AUDIENCE=authenticated

POSTGRES_HOST=your-postgres-host
POSTGRES_DB=postgres
POSTGRES_USER=postgres
POSTGRES_PORT=5432
POSTGRES_SSLMODE=require

PUBLIC_BACKEND_URL=http://localhost:8000

OPENAI_KEY=replace-with-your-openai-key
PLANNER_MODEL=gpt-4o-mini
PROCESSING_LLM_MODEL=gpt-4o-mini
PLANNER_TIMEOUT=60

GOOGLE_CLIENT_ID=replace-with-your-google-client-id
GOOGLE_CLIENT_SECRET=replace-with-your-google-client-secret
MICROSOFT_CLIENT_ID=
MICROSOFT_CLIENT_SECRET=
PLUGIN_OAUTH_SUCCESS_REDIRECT=aiva://oauth/{plugin}/success
PLUGIN_OAUTH_FAILURE_REDIRECT=aiva://oauth/{plugin}/failure

CREDENTIAL_ENCRYPTION_KEY=replace-with-a-fernet-key
CREDENTIAL_ENCRYPTION_KEYS=
CREDENTIAL_ENCRYPTION_ALLOW_PLAINTEXT_FALLBACK=false
```

Generate `CREDENTIAL_ENCRYPTION_KEY` with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Since all developers share the same Supabase DB, everyone on the team must use the **same** key. Share it through the same secure channel used for `SUPABASE_JWT_SECRET`. Production and staging should each have their own separate key.

`CREDENTIAL_ENCRYPTION_ALLOW_PLAINTEXT_FALLBACK` should stay `false`. Only set it to `true` during a controlled migration window if you intentionally need to read legacy plaintext credential rows; fallback reads are logged as warnings.

### Rotating `CREDENTIAL_ENCRYPTION_KEY`

Changing the key without a rotation procedure breaks all existing credentials — every connected user's plugin stops working until they reconnect.

To rotate safely:

1. Generate a new key:
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

2. Switch to `CREDENTIAL_ENCRYPTION_KEYS` (plural) in `.env` — a comma-separated list with the new key first and the old key second:
   ```dotenv
   CREDENTIAL_ENCRYPTION_KEYS=new-key,old-key
   ```
   `MultiFernet` encrypts new writes with the first key and can decrypt rows encrypted with any key in the list, so existing credentials remain readable during the window.

3. Deploy the updated env. No migration needed yet — reads still work with the old key.

4. Re-encrypt all existing rows by running a management command (or a migration) that reads and re-saves every `PluginCredential`. Once complete, all rows are encrypted with the new key.

5. Remove the old key from the list:
   ```dotenv
   CREDENTIAL_ENCRYPTION_KEYS=new-key
   ```
   Or switch back to the single-key form:
   ```dotenv
   CREDENTIAL_ENCRYPTION_KEY=new-key
   ```

6. Deploy again. Rotation complete — the old key is no longer needed.

Important notes:

- backend developers should generate `.env` from [`.env.example`](/Users/samgupta/Github/Aiva/v2/backend/.env.example)
- frontend developers using image-only mode still need a real `.env` file, but it should usually be provided to them by the backend team
- `AIVA_BACKEND_IMAGE` is consumed by `compose.image.yaml`, not Django; it selects the backend image tag to pull
- `AIVA_BACKEND_PORT` is consumed by `compose.image.yaml`, not Django; it controls the local host port mapped to container port `8000`
- `SUPABASE_JWT_SECRET` must match the Supabase project that issued the access token
- `SUPABASE_ANON_KEY` is optional for backend runtime; it is only needed if you use curl, Postman, or `backend/test_login.py` to request a Supabase access token directly
- `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, and `CORS_ALLOWED_ORIGINS` are separate controls: `ALLOWED_HOSTS` validates the backend host header, `CSRF_TRUSTED_ORIGINS` is for trusted CSRF origins, and `CORS_ALLOWED_ORIGINS` allows browser frontends to call the API across origins
- `REDIS_URL` is used by Django cache and as the default Celery broker URL when `CELERY_BROKER_URL` is not set
- `CELERY_BROKER_URL` is used by Celery worker and Beat for scheduled runs; local Docker Compose defaults it to `redis://redis:6379/0`, and non-Docker Celery defaults to `redis://localhost:6379/0` when both broker env vars are blank
- `RUN_MIGRATIONS=false` is set only on worker and Beat containers so the web container remains the startup migration owner
- `PUBLIC_BACKEND_URL` should be `http://localhost:8000` for local Docker testing unless a different externally reachable callback origin is required
- `PLUGIN_OAUTH_SUCCESS_REDIRECT` and `PLUGIN_OAUTH_FAILURE_REDIRECT` are app-return URLs after OAuth completes; they are not the Google callback URI. Use `{plugin}` to generate plugin-specific links such as `aiva://oauth/gmail/success` and `aiva://oauth/google_drive/success`.
- `MICROSOFT_CLIENT_ID` and `MICROSOFT_CLIENT_SECRET` are optional unless Outlook Mail or Outlook Calendar plugins are enabled.

Common Supabase locations:

- `SUPABASE_URL`: Project Settings -> API -> Project URL
- `SUPABASE_ANON_KEY`: Project Settings -> API -> anon/public key; optional for Django runtime, useful for manual token generation
- `SUPABASE_JWT_SECRET`: Project Settings -> JWT Keys -> Legacy JWT Secret
- `SUPABASE_DB_PW`: database password for the project
- `POSTGRES_HOST`: project database host or Supabase pooler host

If Google-backed plugin support is needed:

1. Open the Google Cloud project used for this backend.
2. Enable the Gmail API.
3. Enable the Google Calendar API if calendar support is needed.
4. Enable the Google Drive API if Drive support is needed.
5. Enable the People API if Google Contacts support is needed.
6. Create or reuse an OAuth client.
7. Register these callback URIs for local Docker testing as needed:

```text
http://localhost:8000/plugins/oauth/callback/gmail/
http://localhost:8000/plugins/oauth/callback/google_calendar/
http://localhost:8000/plugins/oauth/callback/google_drive/
http://localhost:8000/plugins/oauth/callback/google_contacts/
```

If Microsoft Outlook plugin support is needed:

1. Create or reuse a Microsoft Entra app registration.
2. Add `MICROSOFT_CLIENT_ID` and `MICROSOFT_CLIENT_SECRET` to `.env`.
3. Register these callback URIs for local Docker testing as needed:

```text
http://localhost:8000/plugins/oauth/callback/outlook/
http://localhost:8000/plugins/oauth/callback/outlook_calendar/
```

## Backend Developer Instructions

Goal: run and edit backend code locally with live reload.

This path uses:

- `docker-compose.yml` as the base (builds the image, exposes port 8000)
- `docker-compose.dev.yml` overlay (bind-mounts source, enables Uvicorn `--reload`, sets `DEBUG=True`)
- Redis, Celery worker, and Celery Beat services for scheduled runs

### 1. Clone the repo

```bash
git clone <backend-repo-url>
cd Aiva/v2/backend
```

If the repo is already cloned:

```bash
cd /path/to/Aiva/v2/backend
```

### 2. Checkout the branch you want

```bash
git checkout <branch>
```

### 3. Create `.env`

```bash
cp .env.example .env
```

Then fill in the real values.

### 4. Start the backend in dev mode

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

What this mode does:

- builds the backend image locally from `Dockerfile`
- mounts your local backend source into `/backend_app`
- starts Uvicorn with `--reload`
- starts Redis, a Celery worker, and Celery Beat for scheduled runs
- runs code from your working tree, not from a frozen image snapshot

The backend is reachable at:

```text
http://localhost:8000
```

To run in the background:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -d
```

### 5. Make code changes

Edit files under `v2/backend`.

Normal Python code changes auto-reflect because:

- the source is bind-mounted into the container
- Uvicorn is running with `--reload`

Celery worker and Beat containers also see the bind-mounted source, but they do not auto-reload like Uvicorn. Restart the Compose stack if you change code that scheduled runs execute.

### 6. Rebuild only when needed

You usually do not need to rebuild for normal Python code changes.

Rebuild if one of these changes:

- `requirements.txt`
- `Dockerfile`
- `entrypoint.sh`
- anything else that affects the image itself rather than only mounted source code

Use:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

### 7. Stop the backend

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml down
```

### 8. Push backend code changes

```bash
git add .
git commit -m "message"
git push
```

### 9. Optional: build and push an image for frontend developers

Use this only when you want frontend developers to test a specific backend revision without cloning the repo.

This repo's GHCR image name is:

```text
ghcr.io/arceus-aiva/aiva-backend
```

You need:

- permission to push packages for the `Arceus-Aiva` GitHub organization
- a GitHub personal access token with `write:packages`
- `read:packages` as well if the package is private

Log into GitHub Container Registry:

```bash
docker login ghcr.io -u <your-github-username>
```

Use the GitHub token as the password.

Build and push a test tag:

```bash
docker build -t ghcr.io/arceus-aiva/aiva-backend:frontend-test .
docker push ghcr.io/arceus-aiva/aiva-backend:frontend-test
```

The frontend runner should normally set `AIVA_BACKEND_IMAGE` to this explicit tag. If you also want `compose.image.yaml` to work with its default image value, publish the same image as `latest`:

```bash
docker tag ghcr.io/arceus-aiva/aiva-backend:frontend-test \
  ghcr.io/arceus-aiva/aiva-backend:latest
docker push ghcr.io/arceus-aiva/aiva-backend:latest
```

Or build and push a tag based on the current commit:

```bash
IMAGE_TAG=$(git rev-parse --short HEAD)
docker build -t ghcr.io/arceus-aiva/aiva-backend:$IMAGE_TAG .
docker push ghcr.io/arceus-aiva/aiva-backend:$IMAGE_TAG
```

Then give frontend developers the image tag and a `.env` file. They can run it with:

```bash
AIVA_BACKEND_IMAGE=ghcr.io/arceus-aiva/aiva-backend:frontend-test \
  docker compose -f compose.image.yaml up
```

Or, for a commit-based tag:

```bash
AIVA_BACKEND_IMAGE=ghcr.io/arceus-aiva/aiva-backend:<commit-sha> \
  docker compose -f compose.image.yaml up
```

## Frontend Developer Instructions

Goal: run the backend from a prebuilt image only, without backend source code.

You do not need the full backend repo for this path. You need:

- `compose.image.yaml`
- a `.env` file (provided by the backend team)
- a Docker image tag (provided by the backend team)

This path starts the backend web service, Redis, Celery worker, and Celery Beat from the prebuilt image. There is no backend source code and no live reload.

### 1. Create a standalone runner folder

```bash
mkdir backend-runner
cd backend-runner
```

### 2. Add the required files

Place these files in the folder:

```text
compose.image.yaml
.env
```

The backend team should provide both files or provide `compose.image.yaml` from the backend repo plus a prepared `.env`.

Set the image tag in `.env`:

```dotenv
AIVA_BACKEND_IMAGE=ghcr.io/arceus-aiva/aiva-backend:frontend-test
```

The `frontend-test` tag is the current shared frontend-development image. The `compose.image.yaml` file defaults to `ghcr.io/arceus-aiva/aiva-backend:latest` only when `AIVA_BACKEND_IMAGE` is omitted. Do not omit it unless the backend team has also published a `latest` tag.

If you want to use a different local host port:

```dotenv
AIVA_BACKEND_PORT=8001
```

If `AIVA_BACKEND_PORT` is omitted, the backend runs on local port `8000`.

### 3. Log into GHCR if the image is private

```bash
docker login ghcr.io -u <github-username>
```

Use a GitHub token as the password. Skip this step if the image is public.

### 4. Pull the backend image

```bash
docker compose -f compose.image.yaml pull
```

### 5. Run the backend

```bash
docker compose -f compose.image.yaml up
```

To run in the background:

```bash
docker compose -f compose.image.yaml up -d
```

To see logs from a background run:

```bash
docker compose -f compose.image.yaml logs -f backend
```

Scheduled-run logs are in the worker and beat services:

```bash
docker compose -f compose.image.yaml logs -f worker beat
```

The backend will be available at:

```text
http://localhost:8000
```

If you changed `AIVA_BACKEND_PORT`, use that port instead.

### 6. Point the frontend at the backend

```dotenv
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
```

Use the equivalent frontend env/config variable for your app.

### 7. Stop the backend

```bash
docker compose -f compose.image.yaml down
```

### 8. Update to a newer backend image

```bash
docker compose -f compose.image.yaml down
docker compose -f compose.image.yaml pull
docker compose -f compose.image.yaml up
```

If the tag changed, update `AIVA_BACKEND_IMAGE` in `.env` before pulling.

This path has no backend source code and no live reload. If backend code changes, pull the new image from the backend team and rerun.

## Verification

These checks apply to both setup paths.

### 1. Get a Supabase access token

The backend does not expose a login endpoint. Authentication comes from Supabase.

**Bash / macOS / Linux** — load `.env` into the shell:

```bash
set -a && source .env && set +a
```

**PowerShell (Windows)** — load `.env` into the session:

```powershell
Get-Content .env | Where-Object { $_ -match '^\w' } | ForEach-Object {
    $key, $val = $_ -split '=', 2
    [System.Environment]::SetEnvironmentVariable($key, $val, 'Process')
}
```

Then request a token. Replace `<user-email>` and `<user-password>` with your Supabase credentials. The `apikey` header below is the Supabase anon/public key (Project Settings → API → anon/public); it is sent to Supabase, not to Django, and is not required in the backend `.env`.

**Bash:**

```bash
curl -X POST "$SUPABASE_URL/auth/v1/token?grant_type=password" \
  -H "apikey: $SUPABASE_ANON_KEY" \
  -H "Content-Type: application/json" \
  -d '{"email": "<user-email>", "password": "<user-password>"}'
```

**PowerShell:**

```powershell
curl -X POST "$env:SUPABASE_URL/auth/v1/token?grant_type=password" `
  -H "apikey: $env:SUPABASE_ANON_KEY" `
  -H "Content-Type: application/json" `
  -d '{\"email\": \"<user-email>\", \"password\": \"<user-password>\"}'
```

Copy the returned `access_token`. Store it for reuse:

```bash
# Bash
export TOKEN="<access_token>"
```

```powershell
# PowerShell
$env:TOKEN = "<access_token>"
```

The remaining examples use `$TOKEN` (Bash) or `$env:TOKEN` (PowerShell). Substitute whichever matches your shell.

### 2. Verify an authenticated backend endpoint

```bash
curl -s http://localhost:8000/projects/ \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

Expected result for a new user:

```json
[]
```

### 3. Create a project

All agent calls are scoped to a project. Create one first:

```bash
curl -s -X POST http://localhost:8000/projects/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "test"}' | python3 -m json.tool
```

Copy the returned `id` and store it:

```bash
# Bash
export PROJECT_ID=<id>
```

```powershell
# PowerShell
$env:PROJECT_ID = "<id>"
```

### 4. Send a simple prompt to the agent

```bash
curl -s -X POST http://localhost:8000/agent/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"prompt\": \"hello\", \"project_id\": $PROJECT_ID}" | python3 -m json.tool
```

Expected result:

```json
{
  "response": "Hello! How can I help you today?"
}
```

### 5. Preview a plan without executing (dry run)

Use `dry_run: true` to see what the agent would do without making any real API calls or sending any emails. Confirmation-required steps are skipped and the response includes a notice:

```bash
curl -s -X POST http://localhost:8000/agent/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"prompt\": \"list my recent emails\", \"project_id\": $PROJECT_ID, \"dry_run\": true}" \
  | python3 -m json.tool
```

### 6. Reset conversation state for a project

Clears the stored chat history and any pending plan for the project:

```bash
curl -s -X DELETE http://localhost:8000/agent/reset/$PROJECT_ID/ \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

Expected result:

```json
{
  "status": "reset"
}
```

After a reset, the next `/agent/` call starts a fresh conversation.

### 7. Verify plugin OAuth if needed

```bash
curl -s -X POST http://localhost:8000/plugins/oauth/connect/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"plugin": "google_drive"}' | python3 -m json.tool
```

Expected result:

- a response containing `auth_url`
- a Google redirect URI using:

```text
http://localhost:8000/plugins/oauth/callback/google_drive/
```

Use `gmail`, `google_calendar`, or `google_contacts` instead if you are verifying those plugins.

## Troubleshooting

**Docker cannot connect to the daemon**

- start Docker Desktop or the Docker daemon
- rerun `docker version`

**Port `8000` is already in use**

- stop the process currently using port `8000`
- or change the host-side port mapping in the compose file you are using

**Backend fails with missing env vars**

- compare `.env` against [`.env.example`](/Users/samgupta/Github/Aiva/v2/backend/.env.example) if you have repo access
- if you are in image-only mode, ask the backend team for a corrected `.env`

**Database connection fails**

- verify `POSTGRES_HOST`, `POSTGRES_DB`, `POSTGRES_USER`, `SUPABASE_DB_PW`, `POSTGRES_PORT`, and `POSTGRES_SSLMODE`
- verify your network can reach the configured Supabase/Postgres host

**Authenticated API calls return `Invalid or expired token`**

- verify the access token is still valid
- verify `SUPABASE_URL` matches the token issuer
- verify `SUPABASE_JWT_SECRET` matches the same Supabase project
- verify `SUPABASE_JWT_AUDIENCE` matches the token's `aud` claim. Supabase user access tokens normally use `authenticated`.

**`/agent/` fails**

- verify `OPENAI_KEY` is set and valid
- inspect container logs:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs -f backend
```

or for an image-only run:

```bash
docker compose -f compose.image.yaml logs -f backend
```

- try a simple prompt like `"hello"` before testing tool-driven prompts

**Scheduled runs stay queued or never run**

- verify Redis, worker, and beat are running:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml ps
```

- inspect worker and beat logs:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs -f worker beat
```

- for image-only mode, use `docker compose -f compose.image.yaml ps` and `docker compose -f compose.image.yaml logs -f worker beat`
- verify `REDIS_URL` and `CELERY_BROKER_URL` point at the same reachable Redis instance

**Gmail OAuth callback uses the wrong URL**

- verify `PUBLIC_BACKEND_URL`
- for local-only Docker testing, `http://localhost:8000` is correct only if Google is actually allowed to redirect there in your setup

**Conversation history or pending plan disappears**

- conversation history and pending plans are stored in the database, not in files
- they persist across container restarts as long as the database connection is unchanged
- if state is missing, check that migrations ran cleanly on startup (`docker logs aiva-backend | grep migrate`)

## Operational Tracking

Use [CHANGELOG.md](/Users/samgupta/Github/Aiva/v2/backend/docs/CHANGELOG.md) for backend runtime, security, config, OAuth, credential, state, and infrastructure changes.
