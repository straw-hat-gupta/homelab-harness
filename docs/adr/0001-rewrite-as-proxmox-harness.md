# ADR-0001: Rewrite as an AI harness for Proxmox home labs, in stages

- **Status:** accepted (2026-10-31)
- **Deciders:** maintainer

## Context

v0 was a Django personal-assistant backend extracted from a failed startup. The [audit](../archive/v0/audit-2026-10-30.md) and its [cross-check](../archive/v0/audit-cross-check-2026-10-31.md) found 20 confirmed defects and 9 more. Most sat in hand-written plumbing: async persistence, retries, confirmation flow, scheduling. About 40% of the code served a mobile product that no longer exists.

The maintainer's goals also changed:
- The project should be a dedicated AI layer for Proxmox home labs (plus Cloudflare, Docker, Linux and Obsidian tasks).
- The maintainer should use it daily.
- It should be easy to extend by asking a coding agent.
- It should demonstrate reliable, observable AI systems to employers.

## Decision

- Rewrite from scratch on a new stack. Don't repair v0.
- Archive v0 at tag `v0-django-final`. Its docs live in `docs/archive/v0/`.
- Deliver in stages. Stage 0 is a complete specification (`docs/spec/`, ADRs, glossary, roadmap) reviewed before any code. Each later stage ends in something the owner uses.
- The v0 failure modes become named reliability requirements ([reliability.md](../spec/reliability.md)).

## Consequences

- There is no runnable code on `main` until Stage 1 lands. That is acceptable, because the maintainer is the only user.
- v0 logic worth keeping (the OAuth state design, MultiFernet rotation, cron and time-zone handling) is ported by reading the tag. It is not resurrected.
- The repository name `agentic-assistant` no longer fits the product. The project is named **homelab-harness**: "Homelab Harness" in prose, `homelab-harness` and `homelab_harness` for packages, and `hh` for the CLI. The decision was made on 2026-11-01 ([roadmap](../roadmap.md#open-decisions), D-1).
