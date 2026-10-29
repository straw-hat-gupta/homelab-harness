# Development

## Local setup

Requires Python 3.13 and Docker (for PostgreSQL; Redis only if you run Celery).

```bash
docker run -d --name aa-pg -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:16-alpine
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` for the local database: `POSTGRES_HOST=localhost`, `POSTGRES_USER=postgres`, `SUPABASE_DB_PW=postgres`, `POSTGRES_SSLMODE=disable`. Generate `CREDENTIAL_ENCRYPTION_KEY`. Placeholder values work for everything else when you are running tests.

```bash
python manage.py migrate
python manage.py runserver            # or: uvicorn backend.asgi:application --reload
```

For background work, start Redis (`docker run -d -p 6379:6379 redis:7-alpine`), set `REDIS_URL=redis://localhost:6379/0`, then run:

```bash
celery -A backend worker --loglevel=info
celery -A backend beat --loglevel=info
```

On macOS, if the worker crashes in `billiard`, add `--pool=solo`. The prefork pool works inside the Linux container.

`docker compose up` builds the image and starts the app, worker, beat, and Redis. It does **not** start PostgreSQL yet, so point `POSTGRES_HOST` at a database you run separately.

## Tests

```bash
python manage.py test                 # full suite (PostgreSQL required)
python manage.py test tools.gmail     # one package
python manage.py test --shuffle       # catch order-dependent tests
```

Discovery is Django's default (`test*.py` under the project), so new test files are picked up automatically. No test calls a real provider: Google clients are mocked, and HTTP calls are patched.

Conventions:
- Run coroutines from sync tests with `backend.testing.run_async`. It closes the executor thread's database connection; plain `asyncio.run` leaks it and breaks test-database teardown.
- Tests that hit throttled endpoints must clear the cache in `setUp` (see `agent/tests/test_views.py`).
- `docs/tools.md` is generated. After changing a tool, run `python manage.py export_tool_reference`. A test fails if you forget.

## Lint

```bash
uvx ruff@0.7.4 check .
```

Rules are in [`ruff.toml`](../ruff.toml): pyflakes plus syntax errors.

## Dependencies

`requirements.in` lists the direct dependencies. `requirements.txt` is the fully pinned lock, compiled by uv. After editing `requirements.in`, run:

```bash
uv pip compile requirements.in --universal --python-version 3.13 -o requirements.txt
```

Dependabot opens weekly PRs for pinned packages and GitHub Actions. CI must pass before merging them.

## CI/CD

| Workflow | Trigger | Jobs |
|---|---|---|
| [`ci.yml`](../.github/workflows/ci.yml) | push to `main`, pull requests, manual, and called by release | **lint** (ruff) · **test** (Django check, `makemigrations --check`, full suite on Postgres 16, result summary) · **secrets** (gitleaks over full history) · **docker** (build the image, run `manage.py check` inside it) |
| [`release.yml`](../.github/workflows/release.yml) | push to `main`, `vX.Y.Z` tags, PRs that touch it or the Dockerfile | Runs `ci.yml`, then builds and pushes `ghcr.io/straw-hat-gupta/agentic-assistant`. On PRs it builds only (dry run). |

Image tags:

| Source | Tags |
|---|---|
| `main` | `edge`, `sha-<short>` |
| `vX.Y.Z` | `X.Y.Z`, `X.Y`, `latest`, `sha-<short>` |

Images carry SBOM and provenance from buildx. The GitHub attestation step runs only once the repository is public (a GitHub requirement for non-Enterprise plans).

### Cutting a release

1. Move the `[Unreleased]` entries in `CHANGELOG.md` under a new version heading, and merge that.
2. Tag the merge commit and push the tag:

   ```bash
   git checkout main && git pull
   git tag -a v0.1.0 -m "v0.1.0"
   git push origin v0.1.0
   ```

3. Watch **Release image** in the Actions tab, then pull the result:

   ```bash
   docker pull ghcr.io/straw-hat-gupta/agentic-assistant:0.1.0
   ```

   While the repo is private, log in first with `echo $TOKEN | docker login ghcr.io -u straw-hat-gupta --password-stdin`, using a token with `read:packages`.
