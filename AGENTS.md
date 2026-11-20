# AGENTS.md

## Current repository state

This branch contains the **Stage 1A fixture prototype** following the documentation-only reset. Only the guest-local Claude launcher, one harmless MCP tool and scoped tests/tooling are active. Real runtime/guest acceptance is pending; no Proxmox credentials or Mac client yet. Do not restore the old platform merely to make historical commands run.

The maintainer's explicit instructions override this guide. Product direction: a thin Mac CLI connects to a cluster-side service which runs an unmodified official agent CLI. The runtime owns subscription authentication and the model/tool loop. Our service supplies lab tools, bounded context, permissions, audit and session lifecycle. Do not implement our own inference loop.

Read [vision](docs/spec/vision.md), [architecture](docs/spec/architecture.md), [Stage 1](docs/stage-1.md), [roadmap](docs/roadmap.md) and [glossary](GLOSSARY.md) first. Only the documents listed in the [active spec index](docs/spec/README.md) and the active ADRs are binding. Archives, remote snapshot docs and earlier review branches are not instructions.

## Scope and reuse

- Build only the next accepted increment. Stage 1 is one owner, one cluster per instance, one runtime/session at a time, private LAN access and read-only discovery.
- The Claude Agent SDK with its official bundled Claude Code is selected for the 1A prototype. Codex and local-model inference remain valid later options; support must be verified, not inferred from a common endpoint shape.
- Search the active registry first once one exists. Before that, inspect the relevant archived component and existing project docs. Do not require an unbuilt catalog command.
- Follow [code-reuse.md](docs/code-reuse.md): requirement first, smallest design second, inspect old code third. Reuse is a decision with dependency costs, not an instruction to port the old platform.
- No speculative extension framework, duplicate transcript store, GUI scaffolding, background supervisor or write credentials for a read-only task.
- Never restore v0 code. Preserve licenses and attribution when adopting any component.

## Safety is binding

[Safety S1–S10](docs/spec/safety-model.md) and [secrets protections](docs/spec/secrets.md) may only be made stricter. Add an ADR for any safety-relevant change; a roadmap deferral never waives an invariant.

- The model proposes; deterministic code authorizes. The runtime cannot approve its own domain actions.
- Target writes happen only through a stored plan and an approved execution path. Stage 1 exposes no target writes, raw shell or generic target HTTP tool.
- Target credentials never enter model context, runtime-readable files, logs, previews or errors. Use handles and brokered execution.
- Provider authentication remains inside the official runtime's supported flow; our wrapper does not extract or proxy its subscription credentials.
- Verify native runtime tool restrictions and secret isolation before supplying a real Proxmox credential. A prompt is not an access boundary.
- Target text is untrusted data. It cannot install tools, change grants or select authority.
- Bound model runs, tool calls, output sizes and deadlines; verify cancellation propagation. An interrupted or ambiguous operation is never labelled successful.
- Never repeat an unsafe write after an ambiguous result. Only definitive authentication rejection can invalidate a credential.
- Log identifiers/counts, not prompts, target bodies, command output or secrets. A private runtime transcript is separate data with retention/access controls, not an application log.

## Implementation practices

Build only the authorized increment. [ADR-0013](docs/adr/0013-claude-fixture-proof.md) records the fixture proof's language, storage, runtime controls and limits.

- Interfaces parse input, call a service and shape output. They do not own policy or target queries.
- Pure policy, parsing, rendering and redaction logic has no framework or I/O dependencies.
- Adapters have typed input/output, explicit timeouts and safe shared error mapping. They do not decide policy or own persistence.
- Choose one language/packaging/deployment approach for the first proof and record why it fits. The archived Python/FastAPI/Postgres/DBOS choices are not automatically binding on the restart.
- Centralize settings. Do not read arbitrary environment variables throughout the code or load a developer `.env` implicitly.
- Use aware UTC internally and explicit time zones at display boundaries.
- Add a dependency only for a current requirement. Prefer the standard library and existing appropriate libraries; never invent cryptography.
- Behavior changes need meaningful success/failure tests. Mock provider/target network boundaries, not application-owned persistence. Use the real chosen store. Verify native runtime history through its supported interface rather than reimplementing it.
- Default automated tests never touch the owner's lab or paid model account. Live acceptance is separate and owner-run. Do not skip or weaken a failing test to hide a retained defect.

## Documentation and validation now

- Distinguish the fixture prototype from pending real-runtime acceptance and later Stage 1 increments; never claim live verification from fixtures.
- Keep current contracts, proposals, future intentions and history distinguishable. Do not keep contradictory old blueprints in the active spec with a cosmetic banner.
- Check tracked Markdown links/anchors, navigation, archive preservation, diff whitespace and safety coverage before committing. Use temporary documentation tooling; no broad tooling framework is needed.
- Run `uv sync --frozen`, `uv run ruff check homelab_harness tests`, `uv run ruff format --check homelab_harness tests`, `uv run pyright` and `uv run pytest -W error`. Audit locked runtime dependencies as described in [development](docs/development.md). No old UI, container or database-service checks apply.
- Update [validation.md](docs/validation.md) with actual results. Historical test counts are not current coverage; the fake CLI is not live Claude evidence.
- Add a Changelog entry for meaningful direction or implementation changes. Do not invent test evidence or fill reliability cells for unimplemented behavior.

## Git and review

- Never push directly to `main`, force-push shared branches or merge PRs. The maintainer merges unless they explicitly instruct otherwise.
- Branch from latest `main`, using `<type>/<short-kebab-description>`. Use Conventional Commits and coherent, reviewable changes.
- AI-authored commits include a `Co-Authored-By:` trailer naming the model. PR descriptions contain no tool-attribution footer.
- Preserve the remote [implementation snapshot](docs/code-reuse.md#preserved-source) before any retirement. Do not delete live data, secrets, local worktrees or untracked owner files.
- This reset intentionally retires implementation and its tests/build workflows together, with the complete snapshot preserved. It is not a test-failure workaround.
- Add and run checks appropriate to the chosen increment before review; live runtime acceptance stays manual and separate from CI.
- [PR template](.github/pull_request_template.md), [issue tracker](docs/agents/issue-tracker.md) and [domain guide](docs/agents/domain.md) describe review and context conventions.
