# Changelog

## [Unreleased]

### Changed

- Reconcile the product as a CLI-first, cluster-hosted wrapper around unmodified official agent runtimes. The runtime owns its subscription login and loop; the harness supplies lab context, typed tools, authorization and session lifecycle.
- Reset the active repository to documentation, legal notices and minimal Git metadata. Source, tests, dependency locks, build/deployment configuration, assets and executable workflows are retired together; the full implementation is preserved at `a97f2aa` on `archive/pre-cli-restart-2026-11-20`.
- Define read-only Stage 1 increments 1A–1E with separate automated, real-model fixture and owner-lab acceptance. GUI, writes and supervision are later intentions.
- Retain safety S1–S10 and secrets protections; disable automatic target-change approval initially. No live integration is claimed verified; the subsequent 1A prototype is listed below.

### Added

- Stage 1A guest-local Claude Agent SDK prototype with bundled official runtime, harness-owned fail-closed tool hooks, one invented-data MCP tool, bounded streaming/cancellation, native-session registration and private SQLite audit. Automated fixture evidence only; subscription/guest acceptance and real Proxmox access remain pending.

- Future host-availability requirement: planned VM migration and cluster-managed recovery after hosting-node failure, with persistent state, stable client reconnection, explicit recovery objectives and no duplicate execution (R-54). Outside Stage 1; not implemented.
- Active ADR-0012, Stage 1 contract, code-reuse policy, future intentions and documentation-validation record.

## Earlier history

The [previous changelog](https://github.com/straw-hat-gupta/homelab-harness/blob/a97f2aacd611f0a6b666f336fda57fad88c27080/CHANGELOG.md) preserves all earlier implementation/dependency changes. The [v0 archive](docs/archive/v0/README.md) covers the earlier Django product. Historical versions and test results do not describe this restart.
