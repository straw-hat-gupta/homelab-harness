# ADR-0007: Owner authentication and the MCP authorization server

- **Status:** accepted (2026-11-01): option A, the embedded single-owner authorization server.

## Context

Remote MCP clients (claude.ai, ChatGPT, Claude Code, Codex) authenticate using OAuth 2.1. Under the 2026-07-28 MCP spec, the harness is a resource server. It must publish protected-resource metadata (RFC 9728), validate resource indicators (RFC 8707), and point to an authorization server that supports Client ID Metadata Documents, with DCR as a fallback. There is exactly one human (the owner), but several clients, each needing its own client ID for audit and revocation.

## Options

| Option | Pros | Cons |
|---|---|---|
| **A. Embedded single-owner AS** in the harness: passkey login, no registration, CIMD + DCR, short-lived tokens | No extra service. Demonstrates auth engineering. Behavior is fully under control. | Security-critical code to write and test. Use a vetted library (for example authlib) and keep scope minimal. |
| **B. Existing lab IdP** (Authentik or Keycloak) | Mature. The lab may already run one. | Heavier. Support for CIMD and resource indicators varies by version (unverified). Another dependency for a fresh install. |

## Decision

**A**, built on a maintained OAuth library, with the token endpoint and login page as the only public auth surface. Interfaces stay pluggable, so B can be added later. The CLI uses a device-flow token from the same AS.

## Implementation notes (2026-11-03)

Built in `packages/core/src/homelab_harness/auth/`, checked against the [MCP 2026-07-28 authorization spec](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization), its [client registration](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/client-registration) and [security considerations](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/security-considerations) pages, and [draft-ietf-oauth-client-id-metadata-document-00](https://datatracker.ietf.org/doc/html/draft-ietf-oauth-client-id-metadata-document-00).

- **The "maintained OAuth library" is the MCP SDK's own authorization-server handlers** (`mcp.server.auth`), not authlib. They already implement the MCP profile: response type `code` only, PKCE `S256` only, exact redirect checks, RFC 8414 and RFC 9728 metadata models, and the `WWW-Authenticate` challenge. authlib would duplicate them and add a dependency. The harness supplies the Postgres-backed provider. Two SDK handlers are replaced: dynamic registration (the SDK mints a client secret and compares it in plain text; the harness registers public clients only) and revocation (the SDK's request model wrongly requires `client_secret`).
- **Passkeys** use `webauthn` (duo-labs/py_webauthn) 3.0.1, with user verification required and no attestation.
- **Tokens are opaque**, 256-bit random, stored as SHA-256 hashes, not JWTs. The resource server is the same process, so a lookup is cheap and revocation takes effect on the next request; a JWT would need a signing key in the vault plus a revocation list. Access tokens live 15 minutes and carry one audience, `<HH_PUBLIC_URL>/mcp`. Refresh tokens rotate on every use; reuse of a rotated one, or of an authorization code, revokes the whole grant.
- **Client identity:** Client ID Metadata Documents are preferred (fetched with SSRF limits; see threat T-20), DCR is the fallback (`HH_OAUTH_DCR_ENABLED`). Either way the owner must consent. Audit labels are `client:cimd:<host>:<path>` and `client:dcr:<id>`.
- **Owner:** one row, enforced by a unique constraint. `homelab-harness-owner enroll` on the host prints a one-time link (the token travels in the URL fragment) and ten recovery codes (scrypt). Recovery codes sign in; adding a passkey needs the host (`--add-passkey`).
- **Deviations:** the CLI still uses an owner bearer token, not a device-flow token; the device flow is a follow-up. Legacy `homelab-harness-token` MCP tokens are still accepted while `HH_MCP_LEGACY_TOKENS=true` (the default for now).

