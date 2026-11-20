# Historical material

Nothing under this directory, on the preserved implementation branch or in earlier review proposals is an active product requirement. The [active specification](../spec/README.md) and [ADR-0012](../adr/0012-managed-agent-runtime-and-cli-first-stages.md) define the restart.

## Control-plane implementation

The full old source and documentation are preserved on [archive/pre-cli-restart-2026-11-20](https://github.com/straw-hat-gupta/homelab-harness/tree/archive/pre-cli-restart-2026-11-20), commit `a97f2aacd611f0a6b666f336fda57fad88c27080`. Its React UI, database, jobs, public MCP/OAuth and broad capability designs are historical references, not mandatory future architecture.

Old ADRs remain readable in [that snapshot](https://github.com/straw-hat-gupta/homelab-harness/tree/a97f2aacd611f0a6b666f336fda57fad88c27080/docs/adr). Their accepted status describes the previous project direction. Current treatment is explicit in ADR-0012; safety/secrets guarantees are carried into the active contracts.

## Django v0

The nine [v0 documents](v0/README.md) remain byte-for-byte unchanged. They describe the personal-assistant product at `v0-django-final`. Relative links among them and external historical source links remain reference material; setup commands there do not apply to this branch. Never restore v0 code.

The [audit](v0/audit-2026-10-30.md) and [cross-check](v0/audit-cross-check-2026-10-31.md) supply lessons about persistence, duplicate execution, unsafe retries, model-classified approval, content leakage and misleading test coverage. Keeping those lessons does not reintroduce Gmail/calendar/contact features.
