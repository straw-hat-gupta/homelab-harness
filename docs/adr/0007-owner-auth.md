# ADR-0007: Owner authentication and the MCP authorization server

- **Status:** proposed. The maintainer decides before Stage 1 ends.

## Context

Remote MCP clients (claude.ai, ChatGPT, Claude Code, Codex) authenticate using OAuth 2.1. Under the 2026-07-28 MCP spec, the harness is a resource server. It must publish protected-resource metadata (RFC 9728), validate resource indicators (RFC 8707), and point to an authorization server that supports Client ID Metadata Documents, with DCR as a fallback. There is exactly one human (the owner), but several clients, each needing its own client ID for audit and revocation.

## Options

| Option | Pros | Cons |
|---|---|---|
| **A. Embedded single-owner AS** in the harness: passkey login, no registration, CIMD + DCR, short-lived tokens | No extra service. Demonstrates auth engineering. Behavior is fully under control. | Security-critical code to write and test. Use a vetted library (for example authlib) and keep scope minimal. |
| **B. Existing lab IdP** (Authentik or Keycloak) | Mature. The lab may already run one. | Heavier. Support for CIMD and resource indicators varies by version (unverified). Another dependency for a fresh install. |

## Recommendation

**A**, built on a maintained OAuth library, with the token endpoint and login page as the only public auth surface. Interfaces stay pluggable, so B can be added later. The CLI uses a device-flow token from the same AS.
