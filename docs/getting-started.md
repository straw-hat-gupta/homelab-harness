# Getting started

**There is no runnable quickstart at this documentation-only checkpoint.** `hh`, a service installer and deployment commands will arrive increment by increment. Do not run historical setup commands against this branch or generate credentials merely to make a demo work.

Read [vision](spec/vision.md), [architecture](spec/architecture.md), [Stage 1](stage-1.md) and [onboarding](spec/onboarding.md). The first proof is one official runtime on a manually prepared service guest, with a harmless fixture tool and no Proxmox credential yet.

Before that proof, choose one runtime/version, supported private guest/install method, effective isolation and run limits. Complete subscription login through the runtime's own documented flow. Verify instructions, tool use, streaming, continuation and stopping before connecting real lab access.

Later increments add deterministic discovery, the thin Mac connection, conversational reads and persistence/reconnect. Each must be tried by the owner before advancing. Exact commands and supported versions will be written only when implemented and verified; vendor documentation alone is not a complete Homelab Harness installation guide.

To inspect the prior implementation rather than build the new one, use the [preserved source](code-reuse.md#preserved-source) and that snapshot's own setup documentation. It is a different product shape with different dependencies; its commands and credentials are not the new Stage 1 contract. Never overwrite existing encryption keys, delete volumes or change a running lab to follow a historical guide blindly.
