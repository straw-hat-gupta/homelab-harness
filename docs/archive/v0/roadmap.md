# Roadmap

The goal is a self-hosted personal assistant that:
- watches a job-search mailbox and texts you about interview invitations and recruiting updates;
- keeps interviews on your calendar as they are scheduled, moved, or cancelled;
- delivers natural-language reminders on time;
- runs multi-step tasks across the connected services safely;
- can be installed by another developer with their own credentials.

Milestones are ordered so that each one ends in something usable. Effort figures are rough, in focused days.

## Milestone 1: Interview radar and reminders, installable (≈ 9–13 days)

**Outcome:**
- Clone, fill in `.env`, run `docker compose up`, create the owner account, and connect Gmail and Google Calendar in a browser.
- An SMS arrives within about 2 minutes of an interview invite or recruiting update.
- Interview invites appear on the chosen calendar, and update when they are moved or cancelled.
- `manage.py remind "call Dana tomorrow at 4pm"` sends an SMS at 4 PM local time, even across restarts.

| # | Task | Acceptance |
|---|---|---|
| 1.1 | ~~New repo, fresh history, provenance~~ | Done |
| 1.2 | ~~All tests discovered and passing~~ | Done: one command runs everything, exits 0 on Postgres |
| 1.3 | ~~CI and release workflows~~ | Done: green runs, `edge` image on GHCR |
| 1.4 | **Owner auth.** Django session (admin and pages) plus DRF token (API), `OWNER_EMAIL` enforced, no auto-provisioning, `authenticate_header` so unauthenticated requests get 401. Give `supabase_uid` `default=uuid4` so orchestrator lookups keep working. Remove Supabase settings. | API works with a DRF token; a second user is rejected; auth tests rewritten |
| 1.5 | **Settings and Compose.** Add `OWNER_TIMEZONE` (IANA, required), `OWNER_PHONE`, `TWILIO_*`, `NOTIFIER_BACKEND`, `ASSISTANT_CALENDAR_ID`, `NOTIFY_CATEGORIES`, `QUIET_HOURS`, `GMAIL_POLL_SECONDS`. Compose: `app`, `worker`, `beat`, `postgres` (volume and healthcheck), `redis`. Celery: `acks_late`, `reject_on_worker_lost`, prefetch 1. Default `PLAN_CACHE_TTL=0`. | `docker compose up` from a clean clone reaches a healthy app |
| 1.6 | **Browser OAuth.** `/connect/<plugin>/` (login required). The callback finalizes when `request.user` is the user who started the flow. Gmail scope becomes `gmail.modify`. Add `required_scopes` on `ToolDef`, plus a test that each integration's scopes cover its tools. | Connect a test Google account in a browser; scope-coverage test passes |
| 1.7 | **Notification outbox.** `Notification(kind, body, dedupe_key unique, status, attempts, next_attempt_at, lease_until, provider_sid, last_error)`. Twilio and console backends. Beat task `flush_outbox`. Command `notify_test`. | Tests for dedupe, retry, `uncertain` on read timeout, stale-lease recovery; a real SMS arrives |
| 1.8 | **Reminders.** `Reminder` model. LLM extracts structure, then `zoneinfo` resolves it deterministically. `remind` and `reminders list/cancel` commands. Beat task `dispatch_reminders`. | Frozen-clock tests (relative days, DST both ways, past time); restart and late-delivery tests |
| 1.9 | **Gmail triage.** `MailboxCursor` (historyId). `InboundMessage`, unique per account and message. `history.list` with fallback when the history ID has expired (404). Rules first (ICS, ATS sender domains, keywords), then LLM structured output with no tools. | About 15 fixtures, including duplicates, expired history, and a prompt-injection email that triggers no action |
| 1.10 | **Calendar sync.** `InterviewEvent` keyed by ICS `UID` or thread. Deterministic Google event IDs (409 means it already exists). Always send `timeZone`. Reschedule on a higher `SEQUENCE`; cancel on `METHOD:CANCEL`. | Mocked tests for create, duplicate, reschedule, cancel, and stale sequence; live test on a dedicated calendar |
| 1.11 | **`ask` command and date context.** Interactive confirm loop over `run_prompt`. Pass the current time and `OWNER_TIMEZONE` to the planner. | A planner test asserts the prompt contains an offset-aware timestamp |
| 1.12 | **Docs.** Quickstart, provider setup (Google Cloud consent screen, Twilio), operations. | A fresh Linux VM install by following the docs works |

## Milestone 2: Tool correctness and failure recovery for all 60 tools and 7 integrations (≈ 6–9 days)

- `ToolDef` gains `required_scopes`, `retry_policy` (`read` / `idempotent_write` / `unsafe_write`), and JSON-Schema argument validation before execution.
- One retry classifier for `requests`, `httplib2`, and socket errors. Honor `Retry-After`. Never retry an `unsafe_write` after an ambiguous outcome (read timeout or 5xx).
- Pass the remaining step budget into each request timeout, so a "timed-out" thread cannot finish a write later.
- Idempotency:
  - Google Calendar: deterministic event IDs.
  - Outlook Calendar: `transactionId`.
  - Notion: dedupe property.
  - Email: no retries after the request was sent.
- Credential refresh with `select_for_update`. One forced refresh and retry on 401. On `invalid_grant`, send a "reconnect" notification.
- Contract tests for every untested tool (success, plus 401/403/404/429).
- `manage.py smoke_test --plugin X [--write]` against real accounts and sandbox resources, with results recorded in `docs/verification.md`.
- Log hygiene: no message content at INFO.

**Accept:** every tool is tested in CI, the scope-coverage test passes, a live smoke run is recorded for each tool, and `docs/reliability.md` maps each recovery behavior to the test that proves it.

## Milestone 3: Safe multi-step chat and automations (≈ 5–8 days)

- Confirm the *resolved* action, not just the summary: run read steps, pause at the first confirmation-required step, and show its actual recipients, body, or time.
- Untrusted-content boundary: delimit tool output in `processing_llm`. Recipients or tools derived from email content always need confirmation.
- Policy for unattended runs: scheduled and direct workflow runs pause at confirmation-required steps unless that workflow explicitly allows the tool. `workflow.save` from chat needs confirmation.
- Fold `tasks` into a single run log. Optional daily digest.

**Accept:** an adversarial test (an injection email tries to reply-all) is blocked and left pending; a scheduled `send_email` pauses for approval.

## Milestone 4: Release (≈ 3–5 days)

- Tag security tests (`@tag("security")`) and add the missing ones: scope coverage, injection, unattended policy, log redaction, owner-only auth, OAuth replay. CI publishes the counts.
- Finish the docs. Make the repo public, which also enables build attestations.
- Tag `v1.0.0`; Compose pins it.

## Behavior rules (for Milestones 1 and 3)

| Action | Automatic? | Condition |
|---|---|---|
| Read mail, classify, store | yes | — |
| SMS to the owner | yes | Category in `NOTIFY_CATEGORIES`. Deduplicated per message. Quiet hours delay non-urgent alerts but not interview invites. |
| Create an event on the assistant calendar | yes | From an ICS invite, or an explicit date, time, and zone with confidence ≥ 0.8. No attendees. Marked as created by the assistant. |
| Update or cancel an assistant-created event | yes, then SMS | Matched by ICS `UID` or thread. |
| Change events the assistant did not create | no | Ask. |
| Send or reply to email, trash, delete, write to Notion, invite attendees | no | Always confirm the resolved parameters. Never triggered by email content alone. |
| Low confidence, a time in the past, or a missing time zone | no | SMS the interpretation and ask. |

**Deterministic code** handles polling, dedupe, ICS parsing, time-zone and DST math, idempotency keys, retries, the outbox state machine, scheduling, policy, and the notification recipient (always `OWNER_PHONE`).

**The LLM** classifies non-ICS mail, extracts fields together with evidence quotes, parses reminder phrasing, plans ad-hoc requests, and writes short summaries. Its output is always validated structured data and never directly causes an external write.

**Edge cases:**
- **Ambiguous dates.** Resolve in `OWNER_TIMEZONE`. Times are assumed by phrase: morning 09:00, afternoon 14:00, evening 19:00. Always echo the result back.
- **DST.** Nonexistent local times shift forward. Ambiguous ones use the first occurrence.
- **Late delivery.** A reminder found late within 6 hours is sent marked "(late)". Later than that, it is marked missed.
- **Expired Gmail history.** Fall back to `newer_than:2d` and re-baseline.
- **Notification outcomes:**
  - 4xx: failed, with no retry.
  - 429, 5xx, or a connection error: retry with backoff, up to 5 attempts.
  - Read timeout: `uncertain`, with no automatic resend.
