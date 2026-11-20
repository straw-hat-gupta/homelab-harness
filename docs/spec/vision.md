# Vision

> **Status: binding target design; not implemented.** Delivery is governed by [Stage 1](../stage-1.md) and the [roadmap](../roadmap.md).

## Product

Homelab Harness is a Proxmox-focused agent workspace and, eventually, supervisor. The owner uses our CLI to connect to a service in the cluster. The service launches an existing official agent runtime with the right lab tools, instructions, facts and limits. It does not implement a competing inference loop.

The Mac is replaceable: it remembers instance connections and its own access, while sessions, native runtime history, provider configuration, secrets and lab memory live on the service guest. One instance manages one cluster. Several saved connections do not imply cross-cluster execution or shared authority.

## First useful result

Ask which Linux containers are running, where guests live, or what CPU, memory and storage a node reports. The agent gathers typed read results and answers with source, units and observation time. Missing or stale data is explicit. An unsupported request to create a VM is refused without seeking broader credentials or improvising a shell command.

Subscription integration means running the unmodified `claude` or `codex` binary, using its supported authentication and programmatic interface. The chosen runtime owns the loop. Our product owns discovery tools, domain permissions, lab context and the lifecycle around that session.

## Principles

- One useful end-to-end increment at a time. Automated checks and owner-lab acceptance precede expansion.
- Deterministic tools collect facts. Owner instructions, observations and untrusted target text remain distinct.
- The runtime manages conversation compaction; we keep lab context bounded, relevant and fresh.
- Credentials stay out of model context. Native runtime tools must not bypass the domain tool boundary.
- Least privilege is enforced at the target, in addition to harness policy.
- Every future write needs a stored plan, deterministic preview, owner authorization where required, verified execution and audit.
- Search/reuse before adding code, but do not inherit archived architecture without a current need.
- Keep the interface thin so a future GUI can use the same core without owning policy.
- Measure task correctness and usability before claiming token savings or Proxmox-UI replacement.

## Long-term intent

Controlled VM provisioning, reusable operations and reviewed tool extensions can follow successful read-only use. A GUI hosted on a cluster guest can later expose sessions, roles/jobs, widgets and actions through the same core. Additional runtimes and local/VPS models are future options. See [future.md](../future.md); no frontend framework or complete supervisor platform is required now.

## Initial non-goals

No GUI, target writes, generated-code execution, multiple agents, unattended jobs, collectors on every node, public endpoint, federation or extra infrastructure domains. No universal runtime abstraction, model gateway, custom conversation compactor or custom subscription-auth implementation. No claim that every model/runtime pairing has equivalent capabilities.
