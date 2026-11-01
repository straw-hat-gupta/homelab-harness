# Specification

The full design for the rewrite. Read it in this order:

1. **[vision.md](vision.md):** what the harness is, its principles, and its non-goals.
2. **[architecture.md](architecture.md):** components, code layout, and the plan, approve, apply flow.
3. **[safety-model.md](safety-model.md):** the binding invariants, risk tiers, previews, and approvals.
4. **[threat-model.md](threat-model.md):** assets, trust boundaries, and threats mapped to mitigations.
5. **[clients.md](clients.md):** how Claude and ChatGPT connect using the owner's own subscriptions.
6. Capabilities:
   - [proxmox.md](capabilities/proxmox.md)
   - [linux-docker.md](capabilities/linux-docker.md)
   - [cloudflare.md](capabilities/cloudflare.md)
   - [obsidian.md](capabilities/obsidian.md)
7. **[steering.md](steering.md):** the steering pack that makes connected models expert operators.
8. **[observability.md](observability.md):** traces, metrics, logs, audit, and client usage.
9. **[reliability.md](reliability.md):** requirements R-01 to R-33, each with a test.
10. **[testing-and-evals.md](testing-and-evals.md):** the test pyramid, the contract kit, and eval tiers.
11. **[extending.md](extending.md):** how to add a capability without touching the core.
12. **[ui-vision.md](ui-vision.md):** the web UI planned after v1 (terminals, dashboard widgets, live usage).

Related:
- [ADRs](../adr/)
- [Glossary](../../GLOSSARY.md)
- [Roadmap](../roadmap.md)
- [v0 archive](../archive/v0/README.md)

**Conventions:**
- Each spec doc starts with a status banner.
- Facts not verified against a primary source are marked "(unverified)".
- When code lands, the matching spec section either becomes the "how it works" doc or is updated to match the code, in the same PR.
