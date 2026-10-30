What this repo does: This is a Django backend that turns a user's request into an LLM-generated plan and runs it through registered tools. It stores conversations, integration credentials, contacts, saved workflows, schedules, and execution records. This audit assumes one self-hosting owner, a web process, Celery workers, and occasional overlapping requests; it does not assume a large public service.

# Repository audit — 2026-10-30

Audited commit: [`658e5f3c8b9edf50efb33433c1d58e42a7ddda4e`](https://github.com/straw-hat-gupta/agentic-assistant/commit/658e5f3c8b9edf50efb33433c1d58e42a7ddda4e), fetched from `origin/main`. This document is the only repository change made for the audit. All fixes below are proposals.

## Overall assessment

**Keep the Django project and its existing app boundaries. The folder layout is a good foundation; the implementation is not yet cohesive or safe enough for unattended writes.** The main problem is that several places own fragments of the same operation: validation, confirmation, conversation state, scheduling, and run tracking. Moving those rules to their existing domain's services will help more than renaming folders or introducing another architecture.

There is removable code, but the evidence does not support deleting large parts of the application as unused. The registry makes all 60 tools reachable, the REST routes expose the older project/contact/task features, and the dependencies have actual consumers. The useful cleanup is a modest deletion pass followed by consolidating duplicated rules. Retiring exposed features is a separate product decision.

The README already acknowledges unsafe write retries, unattended confirmation bypass, Gmail scope gaps, mobile OAuth, and incomplete Compose setup. Those remain findings because they affect whether the next features can safely build on this code. Their presence in the roadmap is not evidence that they have been fixed.

## Must fix

### 1. Async chat silently loses database history and pending plans

Sources: [chat entry point](../../agent/views.py#L317-L323), [context lookup](../../agent/chat_context.py#L41-L58), [pending-plan lookup](../../agent/pending_plan.py#L22-L43).

- **What this is:** `run_prompt()` is async, but calls synchronous ORM-backed context and pending-plan helpers directly.
- **Problem:** Django rejects the database access; both lookup helpers catch every exception and return `None`, so a real project appears absent. Probes reproduced empty history, an unread database pending plan, and a newly saved pending plan going into cache instead of the project row; context autosave also silently does nothing.
- **Fix:** Run database operations through `sync_to_async`, including context load/save and pending-plan transitions, and catch only expected lookup failures. Add an endpoint-to-database test that mocks provider calls but keeps persistence real.
- **If we skip it:** Conversations lose continuity and confirmation state depends on cache rather than the promised database persistence; with local-memory cache, another process or restart loses it.

### 2. Write retries and deadlines can produce duplicate or late external actions

Sources: [retry classifier and loop](../../orchestrator/orchestrator.py#L47-L138), [step deadline](../../orchestrator/orchestrator.py#L239-L263), [threaded Outlook send](../../tools/outlook/api.py#L225-L243).

- **What this is:** Every tool uses the same retry loop, and a coroutine deadline wraps provider calls executed in threads.
- **Problem:** A read timeout or 5xx retries a send/create operation even if the provider already committed it; a probe recorded four calls for one ambiguous write. Cancelling the coroutine also cannot stop its running thread, and a controlled probe demonstrated a write completing after the timeout was reported.
- **Fix:** Classify reads, safely repeatable writes, and unsafe writes; retry only where the operation permits it, using provider idempotency keys where available. Bound provider work by the remaining deadline and record ambiguous writes as uncertain instead of inviting a blind resend.
- **If we skip it:** One request can send several emails or create several events, and the user can see a failure before an external action finishes.

### 3. Confirming a pending plan ignores `dry_run`, and confirmation is not claimed atomically

Sources: [confirmation branch](../../agent/views.py#L337-L380), [fresh-plan dry run](../../agent/views.py#L479-L502), [pending store](../../agent/pending_plan.py#L46-L88).

- **What this is:** Fresh requests and pending confirmations follow different execution branches.
- **Problem:** `{"prompt":"yes","dry_run":true}` reaches `execute()` without `dry_run=True` when a plan is pending; this was reproduced with a mocked executor. Pending load, intent classification, and clear are also separate operations, so two overlapping confirmations can both load and execute the same plan.
- **Fix:** Propagate dry-run behavior in every branch and claim a pending plan once using a short database transition before execution. Use an explicit approval tied to the stored plan/version rather than letting an LLM classification be the only approval signal.
- **If we skip it:** A preview request can perform the action, and a double submission can perform it twice.

### 4. Confirmation is outside the shared executor and approves unresolved actions

Sources: [summary approval](../../agent/views.py#L479-L489), [workflow runner](../../workflows/runner.py#L43-L64), [processing prompt](../../tools/processing_llm/tool.py#L68-L93), [workflow save registration](../../tools/workflows/api.py#L154-L156).

- **What this is:** Chat checks confirmation flags before execution; direct and scheduled workflows call the executor without an equivalent policy check.
- **Problem:** A schedule containing `gmail.send_email` runs without approval, and chat approves an LLM-written summary before reads and text transformations resolve the actual recipient/body. Raw mail or web text can influence a later processing step's output that feeds an already approved write; `workflow.save` also persists plans without confirmation.
- **Fix:** Enforce policy at the shared execution boundary, pause before a protected write, and show its resolved account, recipient, body, or event details. Default unattended writes to pending approval, and treat source content as data rather than authority to select an action.
- **If we skip it:** A new caller or scheduled workflow bypasses chat's protection, and the action performed can differ from the action the owner believed they approved.

### 5. Disabling a user does not revoke API access

Source: [custom authentication](../../authentication/authentication.py#L189-L214).

- **What this is:** Supabase authentication verifies a token and returns its synchronized local user.
- **Problem:** It never checks `user.is_active`; a database probe authenticated an inactive user successfully. Any otherwise valid Supabase identity is also provisioned, which is a documented mismatch with the intended single-owner deployment, not a demonstrated cross-user data leak.
- **Fix:** Reject inactive users immediately and implement the owner-auth migration already planned in roadmap 1.4. Check HTTP and streaming entry points against the same authentication policy.
- **If we skip it:** Turning off a local account does not stop its tokens from accessing the API, and public registration remains available wherever the upstream Supabase setup permits it.

### 6. Plans are not validated against tool contracts before side effects

Sources: [plan schema](../../planner/schemas.py#L8-L41), [deep validation](../../workflows/scheduling.py#L127-L158), [executor](../../orchestrator/orchestrator.py#L190-L246), [processing schema](../../tools/processing_llm/tool.py#L108-L125).

- **What this is:** Pydantic validates the plan envelope, while tool parameters remain arbitrary dictionaries; the deeper workflow validator checks names and references only.
- **Problem:** A plan with valid early writes and missing required parameters in a later step passes validation and fails after the writes; a probe reproduced this. The registry also declares `processing_llm.inputs` optional although its function requires it, and duplicate step IDs/output variables and undeclared `$input` names are not rejected.
- **Fix:** Give all entry points one preflight validator for plan structure, reference order, reserved fields, and tool argument contracts, with deferred references type-checked after resolution. Correct existing schema/function mismatches and reject invalid plans before the first side effect.
- **If we skip it:** A malformed LLM or saved plan partly executes, then returns a failure that can tempt the user to repeat already completed actions.

### 7. Scheduled execution has no reliable claim or dispatch recovery

Sources: [dispatch transaction](../../workflows/tasks.py#L39-L87), [worker execution](../../workflows/tasks.py#L103-L144), [execution model](../../workflows/models.py#L131-L162).

- **What this is:** The dispatcher commits queued execution rows and advances the schedule, then publishes Celery messages; the worker unconditionally marks any supplied execution ID running.
- **Problem:** Replaying a completed execution runs it again, and changing the schedule's workflow after enqueue makes the worker run the new workflow while the execution row still names the old one; both were reproduced. A process crash between commit and publish strands a queued row because no recovery scan exists.
- **Fix:** Claim only a queued execution under a row lock, execute the workflow recorded on that execution, and define whether queued plans are snapshots or current revisions. Recover unpublished queued rows through the existing periodic dispatcher, retaining the same execution identity and avoiding automatic replay of ambiguous writes.
- **If we skip it:** Schedules can duplicate actions, silently miss a run, or execute a different workflow from the one recorded in their history.

### 8. Conversation sequencing, pruning, and clearing disagree

Sources: [database append](../../agent/chat_context.py#L112-L136), [pruning cursor](../../agent/chat_context.py#L263-L288), [context endpoints](../../context/views.py#L63-L104), [model constraints](../../context/models.py#L28-L33).

- **What this is:** Chat and the context API independently append messages and maintain an active-history cursor.
- **Problem:** Two first appends lock no existing row and can both insert sequence 1; a two-connection Postgres probe reproduced this, and no unique constraint prevents it. Other probes showed a clear leaving the old cursor so new messages stay hidden, and pruning the last saved message allowing it to reappear on reload.
- **Fix:** Use one conversation service that locks the owning project before append/reset/prune and enforces unique `(project, sequence)` values. Advance the cursor past every pruned saved row and reset it when all history is cleared; check existing duplicates before adding the constraint.
- **If we skip it:** Messages become unordered, disappear from context, or return after pruning, making later plans depend on the wrong history.

### 9. Temporary credential failures become permanent disconnects

Sources: [refresh and active lookup](../../plugins/services/credentials.py#L82-L172), [orchestrator credential loading](../../orchestrator/credentials.py#L11-L29), [OAuth callback](../../plugins/views.py#L195-L228).

- **What this is:** Credential refresh runs before tools execute, and any refresh exception changes the row to `status="error"`.
- **Problem:** A temporary connection failure makes future active-credential lookups refuse the account; this was reproduced. Refresh is not locked across web/worker processes, while the OAuth callback catches HTTP status errors but lets connection/timeouts escape after consuming the single-use state.
- **Fix:** Mark credentials unusable only on a definitive provider rejection, retain them through transient outages, and serialize refresh per credential while rechecking expiry. Map callback transport failures to a safe reconnect result and explicitly tell the user to restart that consumed flow.
- **If we skip it:** A brief outage requires manual reconnects, concurrent refreshes can race, and OAuth can end in an unexplained server error.

### 10. Sensitive content and provider error details escape their intended boundary

Sources: [Gmail query logs](../../tools/gmail/api.py#L230-L260), [Outlook send logs](../../tools/outlook/api.py#L241-L243), [Notion error body](../../tools/notion/api.py#L36-L45), [workflow error return](../../workflows/runner.py#L80-L82), [audit parameter persistence](../../orchestrator/orchestrator.py#L288-L292).

- **What this is:** Provider tools log search terms, subjects, names, and event titles; raw exception strings flow through orchestration and workflow responses.
- **Problem:** Normal INFO logs disclose mail/calendar content despite the contributor rule, and the supposed redacted audit summary only removes `token_data`, retaining message bodies and recipients. Requests errors can contain a URL with query credentials such as OpenWeather's `appid`, while Notion explicitly embeds the provider response body in its exception.
- **Fix:** Log IDs, status classes, and counts; store an allowlisted action summary instead of sliced raw parameters. Convert provider exceptions to safe structured errors before logs or API responses, and test with a distinctive fake secret/body to prove it never reaches those surfaces.
- **If we skip it:** Operational logs, audit rows, and error responses can expose content or credentials beyond the storage locations the owner expects.

### 11. Integration capabilities and account identity are not enforced consistently

Sources: [OAuth registry](../../plugins/plugins/registry.py#L4-L65), [account lookup fallback](../../plugins/views.py#L223-L237), [credential finalization](../../plugins/services/credentials.py#L389-L408), [Gmail registrations](../../tools/gmail/api.py#L1181-L1208).

- **What this is:** The planner sees registered tools for a connected integration, but no per-tool required-scope check exists; OAuth stores configured scopes and may finalize with no account ID.
- **Problem:** The documented Gmail readonly/send grant does not cover the advertised modify/trash/draft operations. Google Calendar has no account-identity endpoint in the registry, and failed identity lookups elsewhere are ignored, so reconnecting a second unidentified account updates the same `(user, plugin, NULL)` credential slot.
- **Fix:** Declare and enforce required scopes per tool, store actual grants, and request the minimum covering grant as planned in roadmap 1.6. Resolve a stable provider account ID or explicitly support only one account for that integration; do not present unidentified overwrites as multi-account support.
- **If we skip it:** Exposed tools fail on permission errors, and connecting an account can replace another connection without a distinct account choice.

## Should fix

### 12. HTTP write endpoints bypass their serializers

Sources: [contact writes](../../contacts/views.py#L22-L36), [project create serializer](../../projects/serializers.py#L4-L16), [project updates](../../projects/views.py#L63-L98), [workflow writes](../../workflows/views.py#L79-L113), [action limit](../../agent/views.py#L650-L678).

- **What this is:** Some endpoints validate with DRF serializers; others directly index dictionaries, call `.strip()`, or write model attributes.
- **Problem:** Probes reproduced HTTP 500 for `POST /contacts/ {}` and successful project creation with `plugins:["gmail"]`, which later crashes the plugin reader. Negative action limits, non-string workflow names, invalid update types/lengths, and duplicate contact connections also reach unchecked operations rather than consistent validation errors.
- **Fix:** Use the existing serializers for create/update and add small request serializers for workflows/schedules; put the plugin mapping validator on the serializer used by both project paths. Validate bounds and map expected uniqueness conflicts to a safe 4xx response.
- **If we skip it:** Ordinary bad input produces server errors or invalid saved data that breaks later requests.

### 13. Gmail pagination skips messages and shares cursors across accounts

Sources: [cursor storage](../../tools/gmail/api.py#L170-L231), [message pagination](../../tools/gmail/api.py#L233-L283), [next-page tool](../../tools/gmail/api.py#L478-L514).

- **What this is:** Gmail fetches pages into a local list, trims to the requested limit, and caches the provider's next-page token under the user ID.
- **Problem:** With `max_results=150`, it requests 100 plus 100, returns the first 150, then resumes after all 200: a probe demonstrated the skipped 50. Searching another connected account or conversation overwrites the same cursor, and next-page execution can apply that cursor to different account credentials.
- **Fix:** Request only the remaining number of messages on each page and scope cursor state to account and conversation/query identity. Prefer passing the provider cursor explicitly through an existing request context over introducing another global state manager.
- **If we skip it:** “Next page” omits messages or continues the wrong mailbox search.

### 14. The Gmail parser cannot read common nested message bodies

Source: [message parsing](../../tools/gmail/api.py#L55-L130).

- **What this is:** The parser checks top-level plain text or direct multipart children only.
- **Problem:** A `multipart/mixed` message containing `multipart/alternative` and its plain-text body returns `body=""`; this was reproduced. The same shallow traversal misses nested attachments, and HTML-only mail has no body fallback, so a real invite may be reduced to its short snippet.
- **Fix:** Extract the traversal into a pure helper next to the Gmail adapter and walk nested MIME parts, handling base64 padding and an explicit HTML fallback. Use fixtures for nested text, HTML-only mail, attachments, and malformed content before reusing this for mailbox triage.
- **If we skip it:** Summaries and future interview classification operate on incomplete email content without reporting that it is incomplete.

### 15. Calendar adapters do not consistently honor their advertised time behavior

Sources: [Google event listing](../../tools/calendar/api.py#L102-L124), [Google schema promise](../../tools/calendar/api.py#L333-L350), [event construction](../../tools/calendar/api.py#L153-L174), [Outlook listing/free-busy](../../tools/outlook/api.py#L283-L305), [Outlook busy slots](../../tools/outlook/api.py#L448-L462).

- **What this is:** Tools advertise upcoming events, date filtering, recurring events, and free/busy answers.
- **Problem:** Google listing omits the promised default `timeMin=now` (reproduced), and Outlook ignores a single supplied time bound; Google recurring timed events carry no named time zone. Outlook free/busy reports every returned event as busy and silently stops at 100, without consulting `showAs` or following the next page.
- **Fix:** Normalize defaults and validate time bounds before provider calls, supply named zones for recurring timed events, and make free/busy respect availability and pagination. Use provider-boundary contract fixtures, including all-day, recurring, free-status, and DST cases.
- **If we skip it:** “Upcoming” can mean old events, incomplete ranges can be ignored, and availability answers can be wrong; provider acceptance of recurring payloads remains unverified live.

### 16. Saved workflow variables and runtime input validation are incomplete

Sources: [recursive resolver](../../orchestrator/orchestrator.py#L79-L112), [nested workflow contract](../../tools/workflows/api.py#L130-L150), [input validation](../../workflows/scheduling.py#L81-L106), [input coercion](../../workflows/scheduling.py#L165-L207).

- **What this is:** `workflow.save` takes an inner plan with its own variables, and saved workflows accept a small typed input schema.
- **Problem:** The outer resolver descends into the inner plan and tries to resolve `$input.recipient` before that workflow has any inputs, so chat cannot save the documented parameterized plan; this was reproduced. Other probes showed an invalid integer accepted without error and a nonempty list in schema `type` crashing validation; defaults and required/type relationships are also unchecked.
- **Fix:** Preserve inner plan literals until their own execution scope and validate references against that workflow's declared inputs. Reject failed conversions and invalid schema/default values rather than returning the original malformed value; reject schedules that cannot supply required inputs.
- **If we skip it:** Reusable workflows fail during save or execution, while their “typed” inputs give callers a false guarantee.

### 17. Business rules and persistence need clear owners inside the current apps

Sources: [1,015-line agent view module](../../agent/views.py), [workflow HTTP module](../../workflows/views.py), [270-line schedule views](../../workflows/scheduled_views.py), [161-line Celery module](../../workflows/tasks.py), [contact adapters](../../tools/contacts/api.py), [Google contact sync](../../tools/google_contacts/api.py#L140-L226).

- **What this is:** `agent/views.py` owns planning, confirmation, database writes, task tracking, streaming, errors, and HTTP; workflow rules are split among HTTP views, Celery, models, scheduling helpers, and tools.
- **Problem:** A confirmation fix in chat misses schedules, validation differs among entry points, and contact writes in REST/local tools/Google sync use different conventions (`"email"` versus `"Gmail"`) and transaction boundaries. Chat `Task`/`SubTask`, confirmed `AgentAction`, and scheduled execution records also represent different fragments of a run, with no single lifecycle to inspect or resume.
- **Fix:** Move the chat use case to `agent/services.py`, workflow create/update/dispatch/claim rules to `workflows/services.py`, and shared contact writes to `contacts/services.py`; keep adapter functions and Celery tasks thin. Put shared owner-scoped reads in selectors, extract deterministic parsing/validation without Django imports, and define one run-history contract before adding more status models.
- **If we skip it:** Each feature must discover and update several competing implementations, and the same fix repeatedly works through one entry point but fails through another.

### 18. Deployment and configuration still carry unsupported product surfaces

Sources: [Compose](../../docker-compose.yml), [image/entrypoint](../../Dockerfile), [settings](../../backend/settings.py), [contact photos](../../contacts/models.py#L6-L13), [tool key lookups](../../tools/web/api.py#L20-L24), [planner cache key](../../planner/planner.py#L17-L42).

- **What this is:** Compose runs app/worker/beat/Redis, while settings and APIs retain the earlier mobile/product platform assumptions.
- **Problem:** Compose needs a separately configured database and has no app-readiness gate for workers; production admin static assets and uploaded photos have no serving setup, and uploaded files have no persistent volume. Tool keys are read outside settings, OAuth defaults to `aiva://`, the shared async LLM clients outlive per-request sync-view event loops, and history-free plans are cached for an hour without a date/time component.
- **Fix:** Finish the documented minimal owner deployment with Postgres/readiness, explicit static/media handling, centralized settings, and the browser OAuth flow; disable plan caching by default as already planned. Choose one supported async-client lifecycle, and explicitly decide whether contact uploads and mobile-specific surfaces remain supported before maintaining or retiring them.
- **If we skip it:** A successful image check can still yield a broken installation, uploaded photos can disappear on container replacement, and repeated relative-date prompts can reuse stale plans; cross-loop LLM-client behavior needs a focused transport test.

### 19. There is a small, verified deletion backlog and duplicated maintenance logic

Sources: [credential compatibility](../../orchestrator/orchestrator.py#L265-L271), [credential helpers](../../orchestrator/credentials.py), [unused service helper](../../contacts/services.py#L21-L23), [retention commands](../../agent/management/commands), [copied test implementation](../../tools/google_contacts/tests.py#L132-L178).

- **What this is:** Several helpers have no reachable caller or producer, and some maintenance and test code repeats existing logic.
- **Problem:** Full-tree searches found no callers for the inventory below; no current tool produces `updated_token_data`, yet its handler can save refreshed tokens to the newest account rather than the step's selected account. Two purge commands overlap with different default handling, and the Google-contact upsert test carries a second implementation that can pass when production changes break.
- **Fix:** Delete the unused helpers and retired result-token hook together, consolidate the retention behavior with an explicit decision on command compatibility, and replace the copied test body with calls to the actual contact service. Preserve real framework hooks, registered tools, schema migrations, and installed dependencies until their consumers are deliberately retired.
- **If we skip it:** Future maintainers keep reading dead paths, duplicate fixes diverge, and tests can validate the copy instead of the application.

### 20. Passing tests currently overstate coverage of the real boundaries

Sources: [mocked chat persistence](../../agent/tests/test_views.py#L91-L126), [runner test with invalid processing params](../../workflows/tests/test_runner.py#L13-L24), [confirmation-bypass expectation](../../workflows/tests/test_runner.py#L59-L67), [Google contact test copy](../../tools/google_contacts/tests.py#L121-L178), [provider test tree](../../tools).

- **What this is:** The repository has 425 passing tests and working CI, but many tests replace the very boundary where the failures above occur.
- **Problem:** Chat tests mock context/pending storage, runner tests mock the entire executor bridge, and the sync test duplicates its implementation; there is no Outlook-specific test module. Gmail parsing/pagination, Drive content download, refresh races, worker replay, resolved confirmation policy, and DST transitions lack the targeted regression coverage their behavior requires.
- **Fix:** Keep existing useful tests and add a small integration slice through real persistence and orchestration, mocking only HTTP/SDK/LLM providers. Add focused failure-mode and contract cases for the findings above, and replace copied logic or outdated unsafe-policy expectations as each behavior is deliberately fixed.
- **If we skip it:** CI stays green while core flows lose state or perform unsafe writes, and refactors cannot reliably tell whether behavior was preserved.

## Structure to keep, and where future changes should land

The project contains 216 tracked files, including 185 Python files and 30 test modules. Runtime Python is about 11,438 lines, excluding tests and migrations; the large provider modules include substantial tool schemas rather than thousands of independent business rules. These measurements describe the audited commit, before this document.

| Area | Assessment and intended responsibility |
| --- | --- |
| `backend/` | Keep project wiring, settings, middleware, pagination, and Celery setup. Its size does not justify splitting settings into an elaborate package. |
| `authentication/` | Keep the auth domain. Implement owner auth in the existing app and remove Supabase synchronization only with the schema/token migration. |
| `agent/` | Keep conversation-driven planning and approval. Move `run_prompt` and its use-case helpers out of `views.py`; keep HTTP/SSE response handling at the edge. |
| `planner/` | Keep plan schemas, prompts, and LLM planning. A shared plan validator belongs here, with tools/registry metadata as input, rather than inside workflow scheduling. |
| `orchestrator/` | Keep deterministic execution, resolution, approval enforcement, and retry outcomes. Preserve the explicit credential-loading boundary. |
| `plugins/` | Keep OAuth state, encrypted credentials, and token lifecycle services. The `plugins/plugins/registry.py` nesting is awkward but is not itself a defect worth an isolated rename. |
| `tools/` | Keep provider adapters and registry definitions. Extract MIME/normalization helpers when fixing those behaviors; move local database use cases into their owning app services. |
| `contacts/` | Keep address-book ownership and shared mutation logic here. Reconcile connection identifiers before attempting deduplication or deleting existing rows. |
| `projects/`, `context/` | Keep public API and migration compatibility during repairs; use one shared conversation-state service. Merging the apps is unnecessary to fix the current ownership problem. |
| `tasks/`, workflow execution, audit | Keep stored data and routes until run-history semantics are decided. Read/write APIs make `tasks/` live, not dead code; consolidate through a migration and compatibility plan if retiring it. |
| `workflows/` | Keep reusable plans, schedules, and execution history as a domain. Put use cases in services and pure input/cron logic outside views/tasks/models. |
| Docs and delivery | Keep `AGENTS.md`, architecture/configuration/API docs, generated tool reference, dependency lock, CI, secret scan, and release image checks. They already provide useful guardrails. |

A future `assistant/` app is justified by the distinct reminders/triage/outbox domain in the roadmap. It should consume repaired execution and credential services, not import views or copy their rules. There is no evidence here for microservices, a new framework, repository classes around Django's ORM, or an onion/hexagonal rewrite.

## Deletion and consolidation inventory

Searches included application code, tests, migrations, documentation, hidden tracked configuration, string references, and registration/import hooks. “No caller” means none in this repository; external consumers still need a compatibility check before removing a public Python/CLI interface.

| Candidate | Evidence | Action and estimated reduction |
| --- | --- | --- |
| `orchestrator.credentials._list_connected`, `get_connected_plugins` | Only reference chain is wrapper → helper; active code uses `get_connected_accounts`. | Delete both: 30 definition lines. |
| `contacts.services.get_contact_plugin_id` | Definition only. | Delete: 3 lines. |
| `Credentials.safe_dict` | Definition only; APIs use `CredentialReadSerializer`. | Delete: 11 lines. |
| `DisconnectSerializer` | Definition only; route takes credential ID from its URL. | Delete: 2 lines. |
| `CredentialService.validate_state_and_get_user` | Definition only; callback uses `validate_state_and_get_oauth_state`. | Delete: 14 lines. |
| `validate_schedule_fields`, `next_run_for_schedule` | Only caller is one unused helper calling the other; live views use model validators. | Delete together: 11 lines, then remove their unused import. |
| `updated_token_data` hook, `_save_token_data`, `save_credentials` | No producer in any current tool or fixture; hook is the save helpers' only consumer. | Delete together: about 37 lines plus obsolete documentation/imports. |
| `ChatContext.__call__`, `as_transcript`, `to_dict` | Used only by their own facade or tests; actual planner consumes `as_messages`. `from_dict` remains live for DB hydration. | Retire only this unused facade: 23 definition lines, updating/removing only its obsolete API tests. |
| `purge_planner_usage` and `prune_audit_logs` overlap | Both delete `PlannerUsage`; only one also handles actions and their defaults differ. | Keep one retention implementation; roughly 50–75 lines possible, depending on CLI compatibility. |
| Google-contact test `_upsert` copy | Test runs its own approximately 47-line algorithm instead of production's nested function. | Replace with a real-service test; do not merely delete the test. |

The first seven rows account for approximately **108 removable definition/hook lines**, before imports and whitespace. Retiring the test-only facade and consolidating retention bring runtime savings to approximately **180–210 lines**; replacement tests can reduce the net diff. This is an estimate, not a target to meet by deleting useful behavior.

**Dependencies:** All 20 direct requirements have a present purpose; no dependency is proven removable without a feature decision. `Pillow` is required by the live contact `ImageField`, `tiktoken` is used by context budgeting, the Google libraries are directly imported, and Redis/Celery/croniter support existing schedules. Retiring photo uploads could remove Pillow, but that is not an unused-dependency cleanup today.

**Data and contracts to preserve:** Keep merged migrations, including the SavedWorkflow table handoff and context squash/replacements. Do not delete old task/contact/project routes, token fields, integration tools, or migration histories merely because the owner currently uses a smaller subset. In particular, a schema field's absence from internal writes does not prove external clients do not use it.

## Focused performance review

These are concrete contributors to existing findings, not a case for distributed redesign:

| Path | Evidence and smallest response |
| --- | --- |
| Local contact search | `_search_contacts` prefetches connections, but `_contact_to_dict` calls `.values()` on each related manager, which does not consume the prefetched model objects. Serialize `.all()` or prefetch the exact data once; prove query count stays constant as result count grows. |
| Gmail fetch | Up to 500 messages are downloaded sequentially after listing, inside one tool step budget. Use bounded requests/batching and an explicit partial/cursor result instead of starting a batch that is likely to outlive the step timeout. |
| Drive content | `drive_read_file` downloads the whole file into `BytesIO` before applying its 50,000-character cap. Stop reading at an appropriate byte bound and report truncation; output truncation alone does not bound memory or download time. |
| Google contact sync | Fetch-all plus per-person queries/writes can outlast a tool deadline, with non-atomic contact/connection inserts. Move upsert rules into the contact service first, then bound/batch if the actual address-book size needs it. |
| Chat context | Context load fetches every row at/after the cursor and does not prune on hydration. Repair cursor behavior and enforce the budget on load before optimizing token counting. |
| Task creation | `_create_task_record` inserts each subtask separately without a transaction. When retaining this log, create the task and bulk-create its steps atomically inside the owning service. |

## Proposed cleanup order

Each row should be its own concern-sized change or small set of changes, with regression tests and relevant docs. This is a proposed sequence, not authorization to implement it.

| Order | Work | Done when |
| --- | --- | --- |
| 1 | Repair real async persistence and conversation state: findings 1, 3, 8. | Real chat round trips preserve history and pending plans; dry-run never writes protected actions; overlapping requests cannot reuse confirmation or sequence numbers. |
| 2 | Repair execution safety: findings 2, 4, 6, 7. | Unsafe writes are not blindly retried; approval uses resolved parameters; malformed plans fail before writes; queued executions are claimed once and recoverable. |
| 3 | Repair access/credential/content boundaries: findings 5, 9, 10, 11. | Inactive users are rejected, transient outages recover, scopes/account identities are explicit, and fake secrets/content stay out of logs/errors. |
| 4 | Fix adapter/input behavior: findings 12–16. | Malformed HTTP input is 4xx, pagination loses no items, nested MIME works, calendar time contracts are tested, and reusable workflow inputs remain in their own scope. |
| 5 | Consolidate services and delete dead code: findings 17, 19. | Shared rules have one owner; views/tasks/adapters call that owner; only verified unused code is removed. Separate mechanical moves from behavior changes. |
| 6 | Finish the supported owner install and coverage: findings 18, 20. | A clean install reaches a usable app, the supported UI/assets persist and load, and tests exercise real application boundaries with mocked providers. |

Owner authentication can proceed independently early. Safe, no-caller deletions can also be a small separate PR early; avoid mixing them into a safety fix. Keep planned SMS/reminders/triage work in the roadmap until this execution foundation is reliable.

## Verification and audit coverage

Checks ran with Python 3.13.1, the pinned requirements in a temporary virtual environment, and a new isolated PostgreSQL 16 container. No existing application database was used. Provider operations were mocked; no real email was sent and no real account was connected.

| Check | Result |
| --- | --- |
| `uvx ruff@0.7.4 check .` | Exit 0: `All checks passed!` |
| `python manage.py check` | Exit 0: `System check identified no issues (0 silenced).` |
| `python manage.py makemigrations --check --dry-run` | Exit 0: `No changes detected` |
| `python manage.py test --noinput` | Exit 0: 425 tests, 24.325 seconds, `OK` on Postgres 16. |
| `python manage.py test --noinput --shuffle=20261030` | Exit 0: 425 tests, 23.692 seconds, `OK`. |
| Temporary audit probes | Exit 0: 22 checks, 2.545 seconds, `OK`; these assert the observed defects, not that the defects are fixed. |
| `docker build -t agentic-assistant:repo-audit .` | Exit 0. |
| Built image, `manage.py check`, entrypoint overridden | Exit 0; this is a Django boot smoke check, not a full install test. |
| Gitleaks v8.21.2, `git /repo --no-banner --redact` | Exit 0: 14 commits scanned, no leaks found. This does not prove logs are safe or detect all possible secrets. |
| Generated tool reference | Existing `tools.test_reference` passed as part of both suite runs; no regeneration was needed because no tool changed. |

The 22 temporary checks ran outside the repository and left no application or test-file changes. For follow-up implementation, reproduce these cases in committed regression tests that assert the corrected behavior:

| Probe group | Reproduction and observed outcome |
| --- | --- |
| Async persistence — 3 checks | Save one project message/pending plan synchronously, then access the real helper in an async call: history becomes empty, DB pending plan is missed, and pending save writes cache instead of the row. |
| Dry-run — 1 check | Supply an existing pending plan, classify `yes` as confirmation, call `run_prompt(..., dry_run=True)`: executor receives no dry-run flag. |
| Scheduled lifecycle — 2 checks | Execute the same ID twice: runner called twice; change schedule workflow after enqueue: runner gets the new workflow while execution history retains the old ID. |
| Access/refresh — 2 checks | Authenticate a local inactive user: accepted; raise a temporary connection error during refresh: credential becomes `error` and active lookup refuses it. |
| HTTP validation — 2 checks | Create project with `plugins` as a list: accepted then reader crashes; create contact without `first_name`: HTTP 500. |
| Conversation integrity — 3 checks | Synchronize two first appends with separate DB connections: `[1, 1]` sequence values; prune final saved message then reload: old row returns; clear with nonzero cursor then append: new history hidden. |
| Gmail — 2 checks | Mock 100+100 IDs for a 150-message fetch: cursor skips 50; nested plain-text MIME body: empty body returned. |
| Workflow inputs — 3 checks | Invalid integer returns no validation errors; truthy list-valued schema `type` raises `TypeError`; inner `$input.recipient` is resolved prematurely in outer context and raises `KeyError`. |
| Execution contracts — 3 checks | Ambiguous write attempted four times; running thread completes after coroutine deadline; missing later tool parameters pass deep validation and fail after an earlier write. |
| Calendar default — 1 check | List events without time bounds: mocked provider call contains no `timeMin`. |

Coverage included the README and roadmap, all runtime apps and their routes/models/serializers, planner/orchestrator execution, every provider adapter, OAuth/encryption, Celery scheduling, dependency/configuration/build/release files, generated documentation, key migration transitions, and test discovery/scenarios. Tests were inspected especially where they establish or replace these boundaries; the entire suite was executed twice. Initial schema declarations and repetitive schema/test boilerplate were not individually re-proven line by line.

**Verdict:** Keep the current Django layout. Fix persistence and write safety first, then consolidate shared use cases and remove the verified dead paths before adding unattended assistant features.

**Lean: approximately -180 to -210 runtime lines, -0 dependencies possible without retiring a live feature.** Service moves are mostly moves, not savings; broader deletion of task APIs, uploads, or integrations requires a separate compatibility/product decision.

**Not checked:** Live OAuth/provider contracts, real OpenAI transport across request event loops, real Redis/Celery process crashes and redelivery, sustained load, migration upgrades from a populated historical database, full reverse-proxy/TLS/static/media deployment, dependency CVE scanning, and remote CI for this documentation branch. Static findings in these areas are identified as such above; none is a claim of live-provider verification.
