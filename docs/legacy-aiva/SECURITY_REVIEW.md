# Backend Security Review

Date: `2026-05-12`  
Scope: `/Users/samgupta/Github/Aiva/v2/backend`  
Reviewed commit: `2b787e7`

This document summarizes the backend security review findings for the live Django runtime. It separates the originally validated vulnerability from the additional hardening gaps that should still be tracked.

## Executive Summary

- `0` currently open validated high-severity findings from this review.
- `1` previously validated high-severity finding is fixed:
  - OAuth account-link flow could bind a victim Google account to an attacker Aiva account.
- Hardening status:
  - Fixed: JWT audience verification now defaults to and enforces `authenticated`
  - Fixed: agent prompt and project-context message size limits are enforced
  - Fixed: direct HTTP and Google API client calls now use explicit timeout settings
  - Fixed: client-created project-context rows are restricted to `user`
  - Fixed: encrypted credential plaintext fallback is disabled by default and migration-only
  - Fixed: OAuth callback completion now requires an authenticated app-side finalize step before credentials are stored

The most important original finding was the OAuth account-link flow. The backend now uses server-side one-time state plus an authenticated `/plugins/oauth/finalize/` step, so the public provider callback alone cannot create credentials.

## Reportable Finding

### 1. ~~OAuth account-link flow is vulnerable to cross-user token binding~~ Fixed 2026-06-22

- Priority: `P1`
- Severity: `high`
- Confidence: `high`
- CWE: `CWE-352 Cross-Site Request Forgery`
- Affected files:
  - [plugins/services/credentials.py](/Users/samgupta/Github/Aiva/v2/backend/plugins/services/credentials.py)
  - [plugins/views.py](/Users/samgupta/Github/Aiva/v2/backend/plugins/views.py)

#### What was wrong

Current status:

- Fixed: `POST /plugins/oauth/connect/` creates a server-side `PluginOAuthStates` row.
- Fixed: signed provider `state` contains only an opaque nonce.
- Fixed: callback validation checks plugin match, expiry, and unused status.
- Fixed: successful callback consumes the state row exactly once before token exchange.
- Fixed: callback stores encrypted pending token data and returns only an opaque `completion_token` to the app.
- Fixed: credentials are stored only by authenticated `POST /plugins/oauth/finalize/`.
- Fixed: finalize rejects completion tokens when the authenticated user is not the user that started OAuth.
- Fixed: finalize clears pending access/refresh tokens and invalidates the completion token after credential persistence.

Before the finalize split, the callback endpoint was public and used the valid state row to decide which Aiva user received the exchanged Google OAuth tokens. If an attacker started OAuth from their own Aiva account and sent the full provider authorization URL to a victim, the victim could complete Google consent against the attacker's valid state.

Current behavior blocks that path because the provider callback does not write `PluginCredentials`. It redirects with a completion token, and the app must call `/plugins/oauth/finalize/` with bearer authentication. If the victim's app finalizes the attacker's completion token, the backend rejects it because the token belongs to the attacker user.

#### Why this matters

Before the fix, an attacker could:

1. log into their own Aiva account
2. call `POST /plugins/oauth/connect/`
3. get a valid Google OAuth URL containing the attacker’s signed one-time state nonce
4. send that URL to a victim
5. have the victim complete Google consent
6. cause the backend to store the victim’s Google tokens under the attacker’s Aiva account

That can expose the victim’s Gmail or Google Calendar data and actions through the attacker’s account inside Aiva.

#### Code path

State generation and one-time validation:

- [plugins/services/credentials.py](/Users/samgupta/Github/Aiva/v2/backend/plugins/services/credentials.py)
- [plugins/models.py](/Users/samgupta/Github/Aiva/v2/backend/plugins/models.py)

OAuth start endpoint:

- [plugins/views.py](/Users/samgupta/Github/Aiva/v2/backend/plugins/views.py)

Public callback and authenticated credential write:

- [plugins/views.py](/Users/samgupta/Github/Aiva/v2/backend/plugins/views.py)
- [plugins/urls.py](/Users/samgupta/Github/Aiva/v2/backend/plugins/urls.py)

#### Remediation Status

Implemented.

Current controls:

1. `POST /plugins/oauth/connect/` creates a one-time `PluginOAuthStates` row.
2. Provider `state` contains only an opaque signed nonce.
3. `GET /plugins/oauth/callback/<plugin>/` consumes the state once, exchanges the provider code, stores encrypted pending token data, and redirects to the app with a completion token.
4. `POST /plugins/oauth/finalize/` requires bearer auth and verifies the completion token belongs to `request.user`.
5. Successful finalize writes `PluginCredentials`, clears pending access/refresh tokens, and invalidates the completion token.
6. Tests cover replay, expired state, plugin mismatch, legacy state rejection, callback-without-save, successful finalize, refresh-token preservation, and cross-user finalize rejection.

## Hardening Gaps

These did not rise to the same level as the OAuth finding, but they are real weaknesses and should be tracked.

### 2. ~~JWT audience verification is optional~~ Fixed 2026-06-22

- Affected file:
  - [authentication/authentication.py](/Users/samgupta/Github/Aiva/v2/backend/authentication/authentication.py)

Relevant lines:

- [authentication/authentication.py#L19](/Users/samgupta/Github/Aiva/v2/backend/authentication/authentication.py#L19)
- [authentication/authentication.py#L22](/Users/samgupta/Github/Aiva/v2/backend/authentication/authentication.py#L22)

Issue:

If `SUPABASE_JWT_AUDIENCE` was unset, the backend disabled `verify_aud`.

Why it matters:

That is weaker than a strict bearer-token validation policy. The review did not prove an attacker-usable alternate token class from repository evidence alone, so this is documented as a hardening gap rather than a formal vulnerability.

Current status:

- `SUPABASE_JWT_AUDIENCE` defaults to `authenticated`, matching normal Supabase user access tokens.
- `_decode_access_token()` always passes an audience to PyJWT, even if the setting is blank at runtime.
- Tokens with the wrong `aud` are rejected.

### 3. ~~Agent prompt and persisted transcript content are unbounded~~ Fixed 2026-06-22

- Affected files:
  - [agent/views.py](/Users/samgupta/Github/Aiva/v2/backend/agent/views.py)
  - [context/serializers.py](/Users/samgupta/Github/Aiva/v2/backend/context/serializers.py)

Relevant lines:

- [agent/views.py#L31](/Users/samgupta/Github/Aiva/v2/backend/agent/views.py#L31)
- [agent/views.py#L32](/Users/samgupta/Github/Aiva/v2/backend/agent/views.py#L32)
- [context/serializers.py#L4](/Users/samgupta/Github/Aiva/v2/backend/context/serializers.py#L4)

Issue:

There was no `max_length` on:

- `prompt`
- `ProjectContext.content`

Why it matters:

An authenticated user can drive up LLM cost, latency, and worker pressure with very large prompts or transcript entries.

Current status:

1. `AgentRequestSerializer.prompt` is capped at 10,000 characters.
2. `ProjectContextSerializer.content` is capped at 10,000 characters.
3. The remaining recommended follow-up is a per-project transcript-size policy beyond per-message limits.

### 4. ~~External tool calls do not consistently enforce explicit local timeouts~~ Fixed 2026-06-22

- Affected files:
  - [tools/calendar/api.py](/Users/samgupta/Github/Aiva/v2/backend/tools/calendar/api.py)
  - [tools/weather/api.py](/Users/samgupta/Github/Aiva/v2/backend/tools/weather/api.py)
  - [tools/gmail/api.py](/Users/samgupta/Github/Aiva/v2/backend/tools/gmail/api.py)

Issue:

Several external tool calls relied on upstream library behavior instead of explicit local request budgets.

Examples:

- Weather calls used `requests.get(...)` without `timeout=...`

Current status:

- `tools/weather/api.py` now passes an explicit 15-second timeout for current weather, forecast, and coordinate weather calls.
- `tools/google_http.py` provides a shared Google `AuthorizedHttp` transport with an explicit 15-second timeout.
- Gmail, Calendar, Drive, and Google Contacts service builders use that shared bounded transport.
- OAuth/token HTTP calls, web search, planner calls, and processing LLM calls also have explicit timeout settings.

Why it matters:

This is primarily an availability and abuse-resistance gap. Authenticated users can trigger external operations that may tie up request handling longer than intended.

Recommended action:

1. Keep explicit timeout settings on all direct HTTP requests.
2. Keep Google API client builders on the shared bounded transport.
3. Consider per-tool maximum work budgets and circuit-breaking behavior.

### 5. ~~Transcript API allows `system` and `tool` roles~~ Fixed 2026-06-22

- Affected file:
  - [context/serializers.py](/Users/samgupta/Github/Aiva/v2/backend/context/serializers.py)

Relevant lines:

- [context/serializers.py#L20](/Users/samgupta/Github/Aiva/v2/backend/context/serializers.py#L20)
- [context/serializers.py#L21](/Users/samgupta/Github/Aiva/v2/backend/context/serializers.py#L21)

Issue:

The public project-context write path accepted:

- `system`
- `user`
- `assistant`
- `tool`

Why it matters:

In the current model, project owners are writing their own transcript, so this is mostly self-scope. But if transcript writes are ever exposed to less-trusted clients, collaborators, or imported data sources, synthetic `system` or `tool` messages become a prompt-trust boundary problem.

Recommended action:

- Done: client `POST /project-context/<id>/` writes are restricted to `role="user"`.
- Backend code can still create `assistant`, `system`, and `tool` rows internally when needed.

### 6. ~~Encrypted field falls back to plaintext on decrypt failure~~ Fixed 2026-06-22

- Affected file:
  - [plugins/fields.py](/Users/samgupta/Github/Aiva/v2/backend/plugins/fields.py)

Relevant lines:

- [plugins/fields.py#L20](/Users/samgupta/Github/Aiva/v2/backend/plugins/fields.py#L20)
- [plugins/fields.py#L23](/Users/samgupta/Github/Aiva/v2/backend/plugins/fields.py#L23)

Issue:

`EncryptedTextField.from_db_value()` returned the raw stored value if decrypt failed.

Why it matters:

This is survivable during key migration windows, but it can also mask:

- encryption-key drift
- misconfiguration
- accidentally unencrypted stored secrets

Current status:

1. Plaintext fallback is disabled by default.
2. `CREDENTIAL_ENCRYPTION_ALLOW_PLAINTEXT_FALLBACK=true` is required for controlled legacy migration windows.
3. Fallback reads emit a warning through `plugins.fields`.
4. Without the explicit fallback flag, decrypt failures raise instead of silently returning stored token text.

## Areas Reviewed With No Reportable Finding

The review did not surface a cross-user authorization flaw in these live CRUD paths:

- [projects/views.py](/Users/samgupta/Github/Aiva/v2/backend/projects/views.py)
- [context/views.py](/Users/samgupta/Github/Aiva/v2/backend/context/views.py)
- [tasks/views.py](/Users/samgupta/Github/Aiva/v2/backend/tasks/views.py)
- [contacts/views.py](/Users/samgupta/Github/Aiva/v2/backend/contacts/views.py)
- credential query scoping in [plugins/views.py](/Users/samgupta/Github/Aiva/v2/backend/plugins/views.py)
- agent reset and action-audit endpoints in [agent/views.py](/Users/samgupta/Github/Aiva/v2/backend/agent/views.py)

Those endpoints consistently scope object access through `request.user` in the reviewed code.

## Recommended Fix Order

1. Keep the OAuth callback/finalize split intact for all new OAuth-backed plugins.
2. Continue operational hardening with per-tool execution budgets and circuit-breaking beyond request-level timeouts.

## Audit Source

The full scan artifacts and detailed report were generated under:

- `/private/tmp/codex-security-scans/backend/2b787e7_20260512T132112`

That bundle includes the threat model, coverage ledger, validation report, attack-path report, and the original scan report used to produce this document.
