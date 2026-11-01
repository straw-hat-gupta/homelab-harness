# v2 rebuild plan — 2026-10-31

Status: **proposed**. Every decision below is a recommendation that the maintainer still has to confirm. Each phase is sized to fit one or two agent PRs.

This plan has three inputs:
1. The [2026-10-30 audit](../audits/repository-audit-2026-10-30.md), re-checked against the code (section 1).
2. A salvage inventory of the current codebase (section 3).
3. A survey of the late-2026 agent stack. Versions are from PyPI on 2026-10-31.

## Goal

A personal AI assistant that I use every day. It should run on my home lab, be cheap to extend by asking a coding agent, and serve as a portfolio piece that shows I can build **reliable, observable, safe AI products** on a current stack.

What "done" should prove to a reader in five minutes:
- **Safety:** the agent never sends, deletes, or writes without approval of the *resolved* arguments. Crash or retry never duplicates an external write.
- **Observability:** every run is traced end to end (LLM calls, tool calls, cost, latency), and the traces live in a self-hosted backend.
- **Quality is measured:** evals run in CI with thresholds, including a prompt-injection suite.
- **Extensibility is real:** a new capability is one MCP server folder plus one config line. The RAG feature was added exactly that way.
- **Operability:** `docker compose up` on a fresh box gives a healthy stack with one command.

---

## 1. Audit cross-check

Five independent agent passes re-read every cited `file:line`. The full baseline was re-run on Python 3.13.1 against a throwaway Postgres 16:

| Check | Result |
|---|---|
| ruff 0.7.4 | 0 issues |
| `manage.py check` | 0 issues |
| `makemigrations --check` | no changes |
| `manage.py test` | 425 tests, OK (~25 s) |
| `manage.py test --shuffle` | 425 tests, OK |

**All 20 findings are confirmed.** Corrections to the audit:

| Item | Correction |
|---|---|
| #9 credential refresh | It is overstated slightly. `refresh_token` retries connection errors, 5xx, and 429 twice (`plugins/services/credentials.py:115-132`) before the credential is marked `error`. The conclusion still holds. |
| Test-module count | 29 test modules are discovered, not 30. The 30th file is a helper (`contacts/tests/utils.py` or `backend/testing.py`). |
| "All dependencies are fine" | **Not as pinned.** `pip-audit` finds known advisories in 12 locked packages, including PyJWT 2.10.1 (17 advisories, and it verifies the auth JWTs), Django 5.2.7 (30), cryptography 46.0.3 (7), Pillow 12.0.0 (58), and urllib3 2.5.0 (6). The audit didn't run a CVE scan. |

**Issues the audit missed:**

1. **Dry run is not side-effect free.** Only `requires_confirmation` tools are skipped (`orchestrator/orchestrator.py:231`). Under dry run, `workflow.save` still writes to the DB and `processing_llm` still spends tokens.
2. **The confirm path doesn't re-check the plan.** It re-validates plugins only, not tools or contracts (`agent/views.py:358`). Because pending plans silently live in cache (finding #1), a cached plan runs without re-validation.
3. **Approval rests on an LLM classification alone** (`detect_intent`, `agent/views.py:345`). No deterministic token or plan hash backs it. This should be a finding of its own, not a sub-point of #3.
4. **An ambiguous timeout is recorded as "failed"** (`orchestrator/orchestrator.py:252-256`) when the write may have succeeded. That invites a manual resend.
5. **Email content leaks into logs.** Outlook logs `to=` and `subject=` at INFO (`tools/outlook/api.py:243`), and the auth sync logs the user's email at WARNING.
6. **Exception text leaks into stored records and logs.** The raw `str(exc)` is stored in `ScheduledRunExecution.error` (`workflows/tasks.py:77`). Raw enqueue exceptions are logged at WARNING (`:79`) and can contain the broker URL with its credentials.
7. **The encryption data migration ignores key rotation.** It uses single-key `Fernet` (`plugins/migrations/0002_*.py:10-14`), while the runtime field uses `MultiFernet`. A deployment that sets only `CREDENTIAL_ENCRYPTION_KEYS` breaks it.
8. **The planner bypasses settings for its API key** with `os.getenv("OPENAI_API_KEY")` (`planner/planner.py:125`). Separately, `backend/settings.py:12` auto-loads a repo-root `.env`, so a stray file silently changes how tests run.
9. **Dev docs don't mention `ALLOWED_HOSTS`.** With the default `DEBUG=False`, every command fails until it is set.

Confirmed sound, so the design is worth carrying forward:
- OAuth state: signed nonce, single-use DB row, `select_for_update`.
- `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, and CORS defaults.
- No secrets in the tree. Gitleaks and a manual pattern sweep both came up clean.

### What this means

Most of the must-fix findings come from hand-written plumbing:
- an async/sync bridge (#1);
- a retry loop with no idempotency classes (#2);
- a confirmation flow that lives in a view (#3, #4);
- a schema-less tool contract (#6);
- Celery dispatch with no claim step (#7);
- two competing conversation stores (#8).

A current agent framework plus a durable-execution engine provides each of these as a tested primitive. On top of that, about 40% of the runtime code serves a mobile product that no longer exists: Supabase auth, projects, contacts with photos, tasks/subtasks, and `aiva://` redirects.

The audit's verdict ("keep Django, repair in place") is right *under its constraint* of keeping existing behavior. You've removed that constraint, so the recommendation changes.

---

## 2. Decision: rewrite on a new stack and port the valuable logic

**Recommended: rewrite, in this repo**, so CI, history, and provenance stay.
- Tag the current state as `v0-django-final` before removing anything.
- Treat the audit as the **spec for the new system's regression tests**. Each finding becomes a named reliability requirement with a test that proves it. That makes a strong README section: "here are 20 failure modes found in v0, and the test that proves v1 doesn't have them."

The alternative is to repair in place, following the audit's cleanup order. That is lower risk, but it keeps a stack and an architecture that signal 2022, not 2026. It also spends about three weeks fixing plumbing that the new stack replaces.

### Reference stack (Python-first)

| Concern | Choice | Why |
|---|---|---|
| Packaging | **uv** workspace (uv 0.13), **ruff**, **pyright** in CI (ty is still beta; optionally run it alongside) | The current norm. One lockfile for every package. |
| API | **FastAPI** (0.162) with **pydantic-settings** | Async-native, a natural fit with Pydantic AI and MCP, OpenAPI for free. |
| Agent | **Pydantic AI 2.x** (2.64) | Model-agnostic. Typed outputs. Deferred tools with `requires_approval` for human-in-the-loop. Native MCP client. Official durable-execution integrations. |
| Durable execution | **DBOS** (3.4) on Postgres | Agent runs, approvals (wait for an event), cron schedules, and reminders, all in the Postgres you already run. **Replaces Celery and Redis.** Swap in Temporal only if you want that specific signal and accept running another cluster. |
| Data | Postgres 17 with **pgvector**, **SQLAlchemy 2 async**, **Alembic** | One database for state, workflows, and vectors. |
| Tools | **MCP servers** (FastMCP 4.x, streamable HTTP, spec 2026-07-28) | Each integration is its own server. The core is just an MCP client, and you can use the same servers from Claude Desktop or Claude Code every day. |
| Models | Pydantic AI providers: Claude by default, plus OpenAI-compatible **Ollama** or **vLLM** on the home lab. Routing is set per task in config. | Cloud models for planning, local models for classification and embeddings. No gateway needed. If you add LiteLLM later, pin it by hash (versions 1.82.7 and 1.82.8 were malicious, 2026-03). |
| Observability | **OpenTelemetry**, sent to a self-hosted **Langfuse**, plus **structlog** JSON logs | Traces for every LLM and tool call, cost per run, prompt versions. The OTel GenAI conventions are still "Development", so say "OTel-instrumented", not "standards-compliant". |
| Evals | **pydantic-evals** in CI. **promptfoo** or a hand-rolled suite for injection red-teaming. | Quality gates, not just tests. |
| RAG (phase 6) | pgvector plus Postgres full-text search, fused with RRF. Qwen3-Embedding and Qwen3-Reranker on Ollama. | Hybrid search with a reranker is current best practice. A separate vector DB is unneeded for one user. |
| Home lab | **Tailscale** (tailnet-only services, `tailscale serve`), Docker Compose, **SOPS + age** for secrets | Nothing is exposed publicly. Google OAuth uses the loopback (installed-app) flow from the CLI, so no public callback URL is needed. |
| Notifications and approvals on the phone | **ntfy** (self-hosted) or a **Telegram bot** with approve/deny buttons | Replaces the planned Twilio SMS, which is costly and needs A2P registration. You get approvals with a tap. |
| CI/CD | GitHub Actions: ruff, pyright, pytest with testcontainers, evals, gitleaks, pip-audit, Docker build, SBOM and provenance attestation; Renovate | Supply-chain hygiene is part of the pitch. |

The TypeScript alternative is Mastra 1.x or AI SDK 6, Drizzle, and Inngest or Restate. It's coherent, but it throws away the existing Python adapters and Pydantic's validation story. I don't recommend it here.

### Target architecture

```
           phone (ntfy/Telegram)   CLI `aa`   web chat (later)   Claude Desktop/Code
                     │                │             │                  │
                     ▼                ▼             ▼                  │ (direct MCP)
              ┌───────────────── core (FastAPI) ─────────────────┐     │
              │ Pydantic AI agent ── policy gate (deterministic) │     │
              │ DBOS workflows: run · approval · schedule · remind│     │
              │ conversation + run log (Postgres)                 │     │
              └──────┬─────────────────────────────┬─────────────┘     │
                     │ MCP (streamable HTTP, tailnet)                   │
     ┌───────────────┼──────────────┬──────────────┼───────────────┐   │
     ▼               ▼              ▼              ▼               ▼   ▼
 servers/google  servers/notion  servers/homelab  servers/knowledge  Home Assistant
 (Gmail, Cal,    (port)          (Proxmox RO,     (RAG: ingest +     built-in /api/mcp
  Drive)                          Prometheus,      hybrid search)
                                  Uptime Kuma)
                     │
   OTel ─────────────┴──────► Langfuse (self-hosted)      models: Claude API · Ollama/vLLM on lab
```

Key design rules:
1. **Policy is code, not prompt.** Every MCP tool carries `readOnlyHint` / `destructiveHint` / `idempotentHint` annotations, and the core's policy table can override them. Read-only tools run freely. Destructive tools pause the DBOS workflow until a human approves the **exact resolved arguments**. The approval is bound to a hash of those arguments and claimed exactly once, which fixes audit #3 and #4 and the gaps listed in section 1.
2. **Retries are declared, not guessed.** Each tool has a retry class (`read` / `idempotent_write` / `unsafe_write`). Unsafe writes run as a single DBOS step with an idempotency key and are never re-run after an ambiguous outcome; they are recorded as `uncertain` (#2).
3. **One run lifecycle.** A `Run` with its steps is the only execution record. Chat, schedules, and reminders all create runs (#7, #17).
4. **Untrusted content is data.** Tool output from mail or web is wrapped and tagged. A tool call whose arguments derive from untrusted content always needs approval. Eval-tested.
5. **Tools never touch the core DB.** MCP servers own their own storage, such as an encrypted token store.

---

## 3. Strip and port map (current code → v2)

| Current | Fate | Notes |
|---|---|---|
| `tools/gmail`, `calendar`, `drive` | **Port** into `servers/google` | Keep the API-call logic and schemas. Rewrite MIME parsing as a pure, recursive helper with an HTML fallback (#14). Fix pagination (#13), `timeMin` and named zones (#15), and scopes per tool (#11). Deterministic event IDs. |
| `tools/outlook` | **Defer** | Port only if you actually use Microsoft 365. It has no tests today. |
| `tools/notion` | **Port** into `servers/notion` | Stop embedding the provider body in exceptions (#10). |
| `tools/weather`, `tools/web` | Replace | Use existing MCP servers, or about 30 lines each. |
| `tools/memory`, `tools/contacts`, `tools/google_contacts` | Drop and redesign | Memory becomes part of `servers/knowledge`. Contacts aren't needed for v1. |
| `tools/processing_llm` | Drop | Pydantic AI's typed outputs and sub-agents replace a "call an LLM as a tool" step. |
| `tools/workflows` | Redesign | Saved workflows become DBOS workflows. Saving one from chat is a destructive action that needs approval. |
| `planner/`, `orchestrator/` | **Replace** | Pydantic AI plus DBOS plus the policy gate. Keep the *ideas*: whole-value `$ref`s, normalizing to a direct response, and audit on side effects. |
| `plugins/services/credentials.py`, `plugins/fields.py` | **Port the design** | The OAuth state machine, `MultiFernet` with key rotation (add a `rotate-keys` command), and expiry normalization. Mark a credential failed only on `invalid_grant` (#9), and lock refresh per credential. |
| `workflows/models.py` cron and time zones, `workflows/scheduling.py` input schema | **Port the logic** | Becomes DBOS scheduled workflows. Input schemas become pydantic models. Add DST tests. |
| `agent/chat_context.py` | Redesign | Store messages with a unique `(conversation_id, seq)` and budget tokens per model; the current code uses `cl100k`, a GPT-only tokenizer (#8). |
| `authentication/` (Supabase) | **Delete** | Single owner: a Tailscale identity header plus an owner API token for the CLI and bots. Reject everyone else (#5). |
| `projects/`, `context/`, `contacts/`, `tasks/` | **Delete** | Mobile-product legacy. |
| Celery, Redis, DRF, django-environ, Pillow, tiktoken, psycopg2 | **Delete** | Replaced by DBOS, FastAPI, pydantic-settings, and psycopg 3 or asyncpg. |
| `AGENTS.md`, `CLAUDE.md`, CI, gitleaks, release workflow, CHANGELOG, `docs/agents/` | **Keep and rewrite** for the new stack | They are already good guardrails. |
| Audit doc | **Keep** | It becomes the source of `docs/reliability.md`. |

---

## 4. Phased plan

Each phase ends with something usable and has acceptance criteria an agent can verify. Estimates are in focused days.

### Phase 0: Freeze and decide (½ day)
- Tag `v0-django-final`. Bump the locked deps once (`chore(deps):`) so the tag isn't a known-vulnerable snapshot.
- Write ADRs in `docs/adr/`: 0001 rewrite vs. repair, 0002 stack, 0003 MCP-per-integration, 0004 approval policy.
- Turn audit findings #1–#20 and the nine gaps into `docs/reliability.md`. Each row gets an ID (R-01 to R-29), a statement, and a "test:" column that starts empty.
- **Done when:** the ADRs are merged, and the tag and the reliability table exist.

### Phase 1: Skeleton (2–3 days)
- uv workspace layout: `core/`, `servers/_template/`, `packages/shared` (logging, OTel setup, MCP test kit).
- FastAPI app with `/healthz` and `/readyz` (readiness checks the DB and the MCP servers), pydantic-settings, structlog JSON, and OTel auto-instrumentation.
- Compose: `core`, `postgres` (pgvector image, healthcheck, volume), and `langfuse` with its dependencies. Optional `ollama`.
- Alembic baseline, DBOS initialized. Single-owner auth middleware.
- pytest with testcontainers Postgres. CI: ruff, pyright, pytest, gitleaks, pip-audit, Docker build. Renovate.
- Delete the Django apps in a single `refactor!:` PR, separate from the new code.
- Rewrite AGENTS.md for the new layering.
- **Done when:** a clean clone plus `docker compose up` is healthy, a request shows up as a trace in Langfuse, and CI is green.

### Phase 2: Agent core and safety (3–4 days)
- A Pydantic AI agent with model routing from config (`models.yaml`: planner = Claude, classify = local).
- An MCP client toolset loaded from `servers.yaml`.
- A policy gate:
  - It reads the tool annotations and the overrides in `policy.yaml`.
  - Destructive calls go to a DBOS `wait_for_approval` step with the resolved args and their hash.
  - Approval is claimed once. Approvals expire.
- `Run` and `RunStep` tables, a conversation store with a unique sequence, and cost and token accounting per run (exported to Langfuse).
- Untrusted-content tagging for tool outputs.
- `aa` CLI: `aa chat`, `aa runs`, `aa approve <id>`.
- **Done when:** regression tests for R-01 to R-08 (async persistence, retries, dry run, resolved approval, double-submit, plan contracts, conversation sequence) pass. A test kills the worker mid-run, and the run resumes without a duplicate write.

### Phase 3: First MCP servers (3–5 days)
- `servers/_template` holds a FastMCP server, a settings class, an annotations checklist, and a **contract test kit**. The kit runs automatically against every server and checks:
  - the schema is valid JSON Schema;
  - every tool has annotations;
  - error mapping covers 401, 403, 404, 429, and 5xx;
  - logs and errors never contain a planted fake secret or body.
- `servers/google`: Gmail, Calendar, and Drive ported with the fixes in the map above.
  - Loopback OAuth through `aa connect google`.
  - An encrypted token store using MultiFernet with a rotate command.
  - Narrow scopes per tool, enforced by a coverage test.
  - Deterministic Calendar event IDs.
- `servers/homelab`: Proxmox (read-only token), Prometheus queries, and Uptime Kuma status. Configure Home Assistant's built-in MCP server; there is no code to write for it.
- **Done when:** the contract kit is green for every server, and the R-09 to R-15 tests pass.
  - Live smoke tests against a dedicated Google test account are recorded in `docs/verification.md`. Mark anything not verified live as "mocked".

### Phase 4: Durable automations (2–3 days)
- Reminders (`aa remind "call Dana tomorrow 4pm"`):
  - The LLM extracts the structure, and `zoneinfo` resolves the time.
  - A DBOS durable sleep or schedule delivers it.
  - Delivery follows the roadmap's late and missed rules.
- Scheduled workflows on DBOS cron, defaulting to "pause at destructive steps".
- Notification channel: ntfy or Telegram, with approve/deny actions that call `aa approve`.
- First real automation: **mailbox triage → notify**. This is the original "interview radar". Rules run first, then a local-model classification that has no tool access.
- **Done when:** frozen-clock tests (DST in both directions, past times, late delivery) and duplicate-notification tests pass, and you get a real reminder on your phone.

### Phase 5: Evals and observability as features (2 days)
- pydantic-evals datasets in `evals/`:
  - tool selection;
  - argument extraction;
  - reminder parsing;
  - a **prompt-injection suite**, where a malicious email tries to reply-all or exfiltrate and must end blocked or pending.
- A CI job with recorded fixtures for PRs, and a nightly job against real models with score thresholds.
- Langfuse dashboards for latency, cost per run, approval rate, and eval scores. Grafana is optional if the lab already has it.
- Fill every "test:" cell in `docs/reliability.md`.
- **Done when:** a PR that degrades tool selection fails CI, and the reliability table has no empty cells.

### Phase 6: RAG as the proof of extensibility (2–3 days)
- `servers/knowledge`, built by asking an agent to follow the add-a-server skill (below).
  - **Ingest:** a DBOS workflow that chunks Markdown, PDFs, and notes from the NAS or Obsidian vault, with idempotent upserts keyed on content hash.
  - **Search:** pgvector plus full-text search with RRF and a Qwen3 reranker on Ollama.
  - Cites sources in answers.
- A retrieval eval: recall@k on 30 or more real questions.
- **Done when:** the eval scores are published in the README, and the PR shows that adding the feature took no changes to `core/`.

### Phase 7: Showcase (1–2 days)
- README:
  - a one-paragraph pitch and an architecture diagram;
  - a demo GIF (chat, then approval on the phone, then the trace in Langfuse);
  - the reliability table, eval scores, and how to add a capability.
- Make the repo public. Tag `v1.0.0` with a signed image, SBOM, and provenance.
- Optional: a short write-up, "20 bugs I found in my own agent and how v1 prevents them".

**Total: about 16–22 focused days.**

---

## 5. Making it easy to extend with a coding agent

This is the part that makes "add RAG tomorrow" true:
- **One extension point.** A capability is an MCP server folder under `servers/` plus one entry in `servers.yaml`. The core never changes for a new integration.
- **A template plus a skill.** `servers/_template/` is copyable. `.claude/skills/new-mcp-server/SKILL.md` (and the AGENTS.md equivalent) walks an agent through it in order: copy the template, define tools with annotations, add fixtures, run the contract kit, register the server, add an eval case.
- **Contract tests that apply automatically.** A new server inherits the safety checks without writing them, so an agent can't forget them.
- **Policy outside code.** Changing what needs approval means editing `policy.yaml`, which is reviewed and tested, not prompts.
- **Typed config and ADRs.** The agent reads the ADRs plus AGENTS.md and has the rules. Keep AGENTS.md short and binding, and move the details to docs.

## 6. Decisions to confirm

1. **Rewrite vs. repair:** I recommend rewrite (section 2).
2. **DBOS vs. Temporal:** I recommend DBOS. It's simpler on a home lab, and you can still say "durable execution".
3. **Phone channel:** ntfy (self-hosted, homelab-native) or Telegram (richer approve buttons). Pick one for v1.
4. **Integrations for v1:** I recommend Google, Home Assistant, and Proxmox. Defer Outlook and Notion unless you use them daily.
5. **Default model:** Claude for the agent loop, with a local Ollama model for classification and embeddings. Which GPU or box in the lab serves models?
6. **A web UI in v1?** I recommend no. Start with the CLI, phone approvals, and Claude Desktop over MCP, and add a small UI after v1 if you want it.
