# Future intentions

> **Directions, not an implementation backlog or technical blueprint.** Items explicitly marked required later record maintainer requirements for a future stage; other ideas remain optional. The only detailed next-stage commitment is [Stage 1](stage-1.md). Revisit delivery after real use; do not create its scaffolding now.

- **Safe operations:** start with one template-based VM creation workflow. Add other operations only with typed inputs, deterministic previews, required approvals, durable execution and verification.
- **Reusable extensions:** prefer composition of known tools/steps. Agents may later draft standardized additions; reviewing, testing, approving and installing an extension are separate from running a task. Unreviewed generated code never executes against the lab.
- **Cluster-hosted GUI:** use the same service/session/tool/policy core. Start with one useful view or conversation surface. A separately hosted GUI needs explicit authenticated connectivity.
- **Widgets:** reuse data sources and generic visual templates; a new view should often be configuration. No current frontend framework, registry implementation or dashboard library is mandated.
- **Supervision:** named roles, bounded jobs and several runtime sessions managed through a visual interface. Isolation, authority, concurrency and cancellation must be defined before enabling parallel work.
- **More runtimes and inference:** support Codex, local LM Studio/Ollama or VPS inference through an appropriate existing runtime when useful. A raw model endpoint still needs a runtime. Test each exact model/runtime pairing; no universal compatibility promise.
- **Richer context:** compact lab views, targeted refresh and useful runbooks before elaborate sync, collectors, retrieval or vector storage.
- **Other domains:** Linux/Docker, storage/network workflows, Cloudflare, PBS or notes only when an owner task justifies their access and maintenance burden.
- **Remote access and notifications:** future decisions with a separate threat review; not reasons to publish an endpoint or install ntfy/Cloudflare now.

## Required later: harness host availability

The harness must recover on another eligible cluster node when its hosting node fails. Planned maintenance should support VM migration; an already-failed host requires HA restart/recovery, with interruption and client reconnection rather than a promise of uninterrupted live migration. Assess Proxmox's cluster-managed HA first; recovery cannot depend on the agent or wrapper still running on the failed guest. [Proxmox HA documentation](https://github.com/proxmox/pve-docs/blob/master/ha-manager.adoc)

Before enabling this feature, verify:

- Eligible nodes have compatible CPU/guest configuration, network access and spare resources, without a dependency on hardware unique to the failed host.
- VM disks, runtime login/history, memory, broker credentials/keys and audit state remain recoverable through suitable shared or replicated storage. A disk available only on the failed node is insufficient. Define recovery time and allowable state loss before choosing the storage/replication design.
- Quorum and fencing prevent competing active instances. Cluster recovery must operate independently of the harness and must not grant the model additional authority.
- The service returns at a stable address/identity, can reach a surviving trusted Proxmox API endpoint, and the Mac can reconnect without reconfiguring the instance.
- Saved sessions/state recover consistently; interrupted work is reported honestly, and no uncertain target action is automatically replayed.

Acceptance must cover both a planned move and unexpected host loss in a safe test environment, verifying recovered state, client reconnection, exclusive execution and the agreed recovery objectives. Record measured downtime/state loss; do not label this zero-downtime failover. Implementation and infrastructure decisions are deferred; Stage 1 still tolerates hosting-node downtime. This is tracked as R-54 in [reliability](spec/reliability.md).

The previous frontend, orchestration, vault/grant and catalog blueprints are [historical source](code-reuse.md#preserved-source). Their existence does not commit the restart to those designs. Safety and secrets protections remain binding for any future feature.
