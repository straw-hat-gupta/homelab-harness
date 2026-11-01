# Specification

The full design for the rewrite. Read it in this order:

1. **[vision.md](vision.md):** what the harness is (fewer tokens, no discovery, a replacement for the Proxmox UI), its principles, and its non-goals.
2. **[architecture.md](architecture.md):** components, code layout, and the plan, approve, apply flow.
3. **[lab-state.md](lab-state.md):** the deterministic lab model, `lab://` documents, the Git mirror, and centralized logs.
4. **[recipes.md](recipes.md):** reusable, typed, composable operations (Python and script recipes).
5. **[catalog.md](catalog.md):** data sources, widget templates, and the reuse-before-create rule.
6. **[onboarding.md](onboarding.md):** adopting an existing lab with `hh init`, and the lab profile.
7. **[safety-model.md](safety-model.md):** the binding invariants, risk tiers, previews, and approvals.
8. **[threat-model.md](threat-model.md):** assets, trust boundaries, and threats mapped to mitigations.
9. **[clients.md](clients.md):** how Claude and ChatGPT connect using the owner's own subscriptions.
10. Capabilities:
   - [proxmox.md](capabilities/proxmox.md)
   - [linux-docker.md](capabilities/linux-docker.md)
   - [cloudflare.md](capabilities/cloudflare.md)
   - [obsidian.md](capabilities/obsidian.md)
11. **[steering.md](steering.md):** the steering pack that makes connected models expert operators.
12. **[observability.md](observability.md):** traces, metrics, logs, audit, and client usage.
13. **[reliability.md](reliability.md):** requirements R-01 to R-46, each with a test.
14. **[testing-and-evals.md](testing-and-evals.md):** the test pyramid, the contract kit, and eval tiers.
15. **[extending.md](extending.md):** how to add a capability without touching the core.
16. **[secrets.md](secrets.md):** the vault, grants, and how agents use secrets without seeing them, plus owner intake.
17. **[ui.md](ui.md):** the v1 web UI that replaces the Proxmox GUI, built in increments UI-1 to UI-5 on extension registries.

Related:
- [ADRs](../adr/)
- [Glossary](../../GLOSSARY.md)
- [Roadmap](../roadmap.md)
- [v0 archive](../archive/v0/README.md)

**Conventions:**
- Each spec doc starts with a status banner.
- Facts not verified against a primary source are marked "(unverified)".
- When code lands, the matching spec section either becomes the "how it works" doc or is updated to match the code, in the same PR.
