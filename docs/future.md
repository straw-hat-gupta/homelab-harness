# Future intentions

> **Non-binding directions, not an implementation backlog or technical blueprint.** The only detailed next-stage commitment is [Stage 1](stage-1.md). Revisit each idea after real use; do not create its scaffolding now.

- **Safe operations:** start with one template-based VM creation workflow. Add other operations only with typed inputs, deterministic previews, required approvals, durable execution and verification.
- **Reusable extensions:** prefer composition of known tools/steps. Agents may later draft standardized additions; reviewing, testing, approving and installing an extension are separate from running a task. Unreviewed generated code never executes against the lab.
- **Cluster-hosted GUI:** use the same service/session/tool/policy core. Start with one useful view or conversation surface. A separately hosted GUI needs explicit authenticated connectivity.
- **Widgets:** reuse data sources and generic visual templates; a new view should often be configuration. No current frontend framework, registry implementation or dashboard library is mandated.
- **Supervision:** named roles, bounded jobs and several runtime sessions managed through a visual interface. Isolation, authority, concurrency and cancellation must be defined before enabling parallel work.
- **More runtimes and inference:** support Codex, local LM Studio/Ollama or VPS inference through an appropriate existing runtime when useful. A raw model endpoint still needs a runtime. Test each exact model/runtime pairing; no universal compatibility promise.
- **Richer context:** compact lab views, targeted refresh and useful runbooks before elaborate sync, collectors, retrieval or vector storage.
- **Other domains:** Linux/Docker, storage/network workflows, Cloudflare, PBS or notes only when an owner task justifies their access and maintenance burden.
- **Remote access and notifications:** future decisions with a separate threat review; not reasons to publish an endpoint or install ntfy/Cloudflare now.

The previous frontend, orchestration, vault/grant and catalog blueprints are [historical source](code-reuse.md#preserved-source). Their existence does not commit the restart to those designs. Safety and secrets protections remain binding for any future feature.
