# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Repository created from the Aiva backend (`Arceus-Aiva/Aiva@f4733e9`) with fresh history, MIT license, NOTICE, and ORIGINS.
- GitHub Actions CI: lint, Django checks, migration drift check, tests on Postgres, gitleaks, Docker build.
- Release workflow publishing versioned images to GHCR after CI passes; Dependabot for Actions and pip.

### Fixed
- Test discovery now runs all 423 tests (previously 256); suite passes on Postgres with exit code 0.

### Removed
- Supabase login helper, unused prompt/server scripts, dead test helper, and the Aiva GHCR image compose file.
