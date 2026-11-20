# Stage 1: one managed runtime and read-only cluster discovery

> **Status: binding delivery contract; not implemented.** [Project status](project-status.md) is documentation only. Every command or screen below is illustrative until an implementation increment supplies it.

## User experience

The owner manually prepares a dedicated guest in the cluster, sets up one official runtime with a supported subscription login and connects a scoped Proxmox read credential. On the Mac, opening `hh` offers saved harness instances and an add-connection choice. Selecting one verifies its identity and opens that instance's session. The agent runs on the cluster-side service guest.

Initial questions:

- Which cluster nodes are present, and which are reachable?
- Which Linux containers are running, with VMID and node?
- Which VMs are running, and where?
- What CPU counts/utilization and memory total/used/free does this node report?
- What storage is available to this node, with total/used/free and shared-storage identity?

Answers must come from authorized typed reads and include source, units and observation time. A count of CPU cores is not a workload admission policy. Free memory/storage does not prove that a VM will fit. Avoid double-counting shared storage. Unknown, unavailable or stale facts must remain explicit.

A VM-creation request is refused because this release has no mutating target tools, raw shell or generic target HTTP escape hatch. Do not create write credentials in preparation for a later stage.

## Scope

| Included | Excluded |
|---|---|
| One owner, one cluster per instance, one agent and one active run | Teams, federation, multi-agent supervision and unattended jobs |
| Real unmodified vendor CLI, supported subscription login, session continuation and streamed events | Custom inference loop, direct subscription-token proxy, all-runtime compatibility layer |
| Management plus interactive CLI; saved instance selection | GUI, terminals in a browser, widgets and dashboards |
| Manual service-guest preparation and short setup procedure | Automatic guest provisioning or software installation across discovered nodes |
| Small read-only Proxmox registry, brokered credential, verified TLS and audit | Target writes, raw exec, generic network tools and generated tool execution |
| Service-owned observations/owner notes and native runtime history | Vector database, automatic memory editing, duplicate transcript store and Git memory mirror |
| Bounded context, outputs, calls and runtime lifetime; cancellation and honest failure | Full monitoring stack, remote public endpoints, notification services and broad capability packages |

MCP connects the runtime to domain tools locally/private. It does not require publishing a remote server for claude.ai or ChatGPT web. Subscription inference still needs normal outbound vendor connectivity. A browser used for the vendor's login is not a product GUI.

## State placement

| Mac | Service guest |
|---|---|
| Instance aliases/addresses, expected identity and reference to local client authentication | Instance/cluster identity and registered Proxmox endpoint/trust |
| Transient terminal presentation and bounded setup data | Runtime configuration and runtime-managed provider login state |
| No Proxmox credential or authoritative agent memory | Protected target credential, grants and append-only audit |
| Reinstallable without erasing server-side history | Native runtime session/history, owner notes, observed facts and session mappings |

Authentication during setup may require the Mac browser to complete the runtime's documented flow. The wrapper must not read/export the provider credential store. Native runtime state stays on the guest. No secrets are pasted into chat, command-line arguments, reports or public repo examples.

## Increment 1A: runtime and boundary proof

Choose one runtime and one manually prepared guest. Claude Code is the proposed first backend; that recommendation is not a claim of tested support. Launch the actual CLI with supported instructions, one harmless fixture MCP tool and bounded execution. Stream progress/final output and resume the native session.

Before 1B, record owner-run evidence on the guest for subscription login, instruction loading, actual tool use, honest stream/process failure, interruption, session continuation and enforced native-tool/credential isolation. Demonstrate that the agent cannot run unrestricted commands or read protected service credentials. No real Proxmox credential is needed for this increment.

If required controls are unavailable, stop and report the limitation. Assess another official runtime explicitly; do not silently substitute an API key, custom loop, screen scraping or unrestricted execution.

## Increment 1B: deterministic Proxmox discovery

Implement only the typed reads needed for the questions above, without requiring a model to gather facts. Register one endpoint with verified TLS and a read-only token supplied through owner-only intake. Tool-side scope and target ACLs enforce reads. No node software is installed automatically.

Before 1C, compare actual cluster/node/guest/storage identities and numeric units with Proxmox. Record permission gaps without escalating. Exercise malformed responses, timeouts, denied access, partial failures and secret canaries against fixtures; do not break a real node for failure tests. Verify missing sources are not silently omitted and sensitive config fields are excluded before persistence/output.

## Increment 1C: thin Mac connection

Add/select a saved instance, authenticate through one encrypted private connection, display its verified cluster identity and obtain a deterministic discovery result. Management and chat use the same core; the Mac never calls Proxmox directly.

Before 1D, connect from the owner's Mac to the service guest, then reconnect. Wrong server identity and revoked owner access must fail. Test two-instance profile isolation with fixture services; only one real cluster is required. No new public OAuth/registration service is needed merely to prove this connection.

## Increment 1D: end-to-end discovery conversation

Connect the proven runtime to the real restricted tool registry. Supply operator instructions and compact relevant facts. Let the runtime own its iteration and compaction. The wrapper bounds each run; tool execution has independent deadlines/output limits and deterministic validation.

Before 1E, the real model answers the initial questions through actual tool reads. Compare the facts against Proxmox. Record unsupported requests, exhausted limits, interrupted streams and malicious fixture text. Unknown tool names/arguments are refused before target I/O. A model statement that a run is done is not evidence of successful discovery if required tools failed.

## Increment 1E: persistence, refresh and repeatability

Persist runtime/session mapping and native history on the guest. Keep owner-managed notes separate from deterministic observations. Reconnect from a clean CLI and after a service restart. Mark incomplete runs interrupted; do not auto-resubmit a request after losing its response.

Proposed disconnect behavior: interrupt the active read-only run, preserve completed history and require a new owner request to continue. Record the final choice before implementing it. Verify propagation to child processes/tool calls; parent process exit alone is insufficient. Each external call remains deadline-bounded even if client cancellation is lost.

Before declaring Stage 1 accepted, verify saved history survives client replacement and restart; a refresh shows a harmless state change already made by the owner; stale/partial observations remain labelled. Record transcript access/retention and safe export behavior. Never place private lab transcripts in ordinary logs or Git automatically.

## Stage 1 acceptance

All boxes require actual evidence; none is complete today.

- [ ] Fresh manual-guest setup follows the documented procedure and identifies the active runtime/account without exposing credentials.
- [ ] Existing subscription works through the real CLI; no direct provider proxy or silent API-key fallback.
- [ ] Mac connection selection verifies the intended instance/cluster before a message or tool request.
- [ ] The initial questions return correct typed facts, sources, units and timestamps.
- [ ] Unavailable sources and denied privileges produce honest partial/refused results, not fabricated facts or escalation.
- [ ] Native runtime tools cannot bypass the target boundary, read target secrets or use owner-only configuration/approval paths.
- [ ] Invalid calls, malicious target content, repeated failures and exhausted run/context/output budgets terminate predictably.
- [ ] Cancellation, disconnect and restart do not create unbounded orphan work or silently replay interrupted requests.
- [ ] History, observations and owner notes remain on the guest and are distinguishable from each other.
- [ ] Secrets do not appear in model-visible results, terminal output, audit, logs or errors; tool calls have append-only audit outcomes.
- [ ] Requests to create/change guests, run raw commands or install a generated tool are refused.
- [ ] Automated regression evidence, real-model fixture evidence and the owner's lab acceptance are recorded separately.

## Decisions still open

| Decision | Needed before |
|---|---|
| Confirm first runtime/version and supported programmatic control surface | 1A |
| One supported guest/install method and enforceable runtime isolation | 1A |
| Numerical run/time/call/context/output limits and cancellation semantics | 1A; refine with real tool evidence in 1D |
| Credential/audit storage and whether archived vault components justify their dependencies | Before supplying a real target credential in 1B |
| Actual cluster/PVE compatibility and required least-privilege read permissions | 1B |
| One authenticated encrypted client transport and pairing/revocation method | 1C |
| Which private lab data may be sent to the selected vendor model | Before 1D live-model access |
| Disconnect policy, private-history retention and recovery/export procedure | Before those behaviors in 1C–1E |

Use [testing/evals](spec/testing-and-evals.md) and the [validation record](validation.md). Resolve or explicitly accept failures with the owner before the next increment. Do not add implementation or another stage as a workaround for missing acceptance evidence.
