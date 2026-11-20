# Changelog

## [Unreleased]

### Changed

- Reconcile the product as a CLI-first, cluster-hosted wrapper around unmodified official agent runtimes. The runtime owns its subscription login and loop; the harness supplies lab context, typed tools, authorization and session lifecycle.
- Reset the active repository to documentation, legal notices and minimal Git metadata. Source, tests, dependency locks, build/deployment configuration, assets and executable workflows are retired together; the full implementation is preserved at `a97f2aa` on `archive/pre-cli-restart-2026-11-20`.
- Define read-only Stage 1 increments 1A–1E with separate automated, real-model fixture and owner-lab acceptance. GUI, writes and supervision are later intentions.
- Retain safety S1–S10 and secrets protections; disable automatic target-change approval initially. No restarted application or live integration is claimed implemented.

### Added

- Active ADR-0012, Stage 1 contract, code-reuse policy, future intentions and documentation-validation record.

## Earlier history

The [previous changelog](https://github.com/straw-hat-gupta/homelab-harness/blob/a97f2aacd611f0a6b666f336fda57fad88c27080/CHANGELOG.md) preserves all earlier implementation/dependency changes. The [v0 archive](docs/archive/v0/README.md) covers the earlier Django product. Historical versions and test results do not describe this documentation-only checkpoint.
