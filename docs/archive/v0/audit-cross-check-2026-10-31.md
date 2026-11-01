# Audit cross-check — 2026-10-31

This re-checks [the 2026-10-30 audit](audit-2026-10-30.md) against the tag `v0-django-final`. It was done before the rewrite. File references point at that tag.

## Method

Five agents each re-read every `file:line` cited in their part of the audit. The full baseline was then re-run on Python 3.13.1 against a throwaway Postgres 16:

| Check | Result |
|---|---|
| ruff 0.7.4 | 0 issues |
| `manage.py check` | 0 issues |
| `makemigrations --check` | no changes |
| `manage.py test` | 425 tests, OK (~25 s) |
| `manage.py test --shuffle` | 425 tests, OK |

## Corrections

All 20 findings hold up. Three points need correcting:

| Item | Correction |
|---|---|
| #9 credential refresh | Slightly overstated. `refresh_token` retries connection errors, 5xx, and 429 twice (`plugins/services/credentials.py:115-132`) before marking the credential `error`. The conclusion still holds. |
| Test-module count | Discovery finds 29 test modules, not 30. The audit's 30th file is a helper, either `contacts/tests/utils.py` or `backend/testing.py`. |
| "All dependencies are fine" | **Not at the pinned versions.** The audit didn't run a CVE scan. `pip-audit` finds known advisories in 12 locked packages. They include PyJWT 2.10.1 (17 advisories; it verifies the auth JWTs), Django 5.2.7 (30), cryptography 46.0.3 (7), Pillow 12.0.0 (58), and urllib3 2.5.0 (6). |

## Issues the audit missed

1. **Dry run still has side effects.** It skips only tools marked `requires_confirmation` (`orchestrator/orchestrator.py:231`). `workflow.save` still writes to the database, and `processing_llm` still spends tokens.
2. **Confirming doesn't re-validate the plan.** The confirm path checks the plan's plugins only, not its tools or contracts (`agent/views.py:358`). Finding #1 means pending plans quietly live in the cache, so a cached plan runs without re-validation.
3. **Approval depends only on an LLM classification** (`detect_intent`, `agent/views.py:345`). No deterministic token or plan hash backs it. This deserves its own finding, not a sub-point of #3.
4. **An ambiguous timeout is recorded as "failed"** (`orchestrator/orchestrator.py:252-256`), even though the write may have succeeded. That invites a manual resend.
5. **Email content leaks into logs.** Outlook logs `to=` and `subject=` at INFO (`tools/outlook/api.py:243`), and the auth sync logs the user's email at WARNING.
6. **Exception text leaks into stored records and logs.** `ScheduledRunExecution.error` stores the raw `str(exc)` (`workflows/tasks.py:77`). Enqueue exceptions are logged raw at WARNING (`:79`), and they can contain the broker URL with its credentials.
7. **The encryption data migration ignores key rotation.** It uses single-key `Fernet` (`plugins/migrations/0002_*.py:10-14`), but the runtime field uses `MultiFernet`. A deployment that sets only `CREDENTIAL_ENCRYPTION_KEYS` breaks the migration.
8. **Configuration loading has two leaks.**
   - The planner reads its API key with `os.getenv("OPENAI_API_KEY")` instead of going through settings (`planner/planner.py:125`).
   - `backend/settings.py:12` auto-loads a `.env` from the repo root, so a stray file silently changes how tests run.
9. **The dev docs don't mention `ALLOWED_HOSTS`.** `DEBUG` defaults to `False`, so every command fails until it is set.

## What was sound

These parts of the design are worth carrying forward:
- OAuth state: a signed nonce, a single-use database row, and `select_for_update`.
- The defaults for `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, and CORS.
- No secrets in the tree. Gitleaks and a manual pattern sweep both came up clean.

## Conclusion

Most of the must-fix findings come from hand-written plumbing:
- an async/sync bridge (#1);
- a retry loop with no idempotency classes (#2);
- a confirmation flow that lives in a view (#3, #4);
- a tool contract with no schema (#6);
- Celery dispatch with no claim step (#7);
- two competing conversation stores (#8).

A current agent framework plus a durable-execution engine provides each of these as a tested primitive. About 40% of the runtime code also serves a mobile product that no longer exists: Supabase auth, projects, contacts with photos, tasks and subtasks, and `aiva://` redirects.

The audit recommended keeping Django and repairing it in place. That was right given its constraint of preserving existing behavior. The maintainer dropped that constraint and chose a rewrite; see `docs/adr/` once the rewrite docs land.
