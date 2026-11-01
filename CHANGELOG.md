# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Removed
- **BREAKING:** the v0 Django/DRF/Celery backend (all apps, dependencies, Docker image, Compose files, and the release workflow) is removed from `main` ahead of a rewrite. It is preserved at tag `v0-django-final`; its docs, the 2026-10-30 audit, and its 2026-10-31 cross-check moved to `docs/archive/v0/`.

### Changed
- CI checks documentation links and scans for secrets until code returns. Dependabot watches GitHub Actions only.

### Added
- Repository created from the Aiva backend (`Arceus-Aiva/Aiva@f4733e9`) with fresh history, MIT license, NOTICE, and ORIGINS.
- GitHub Actions CI: lint, Django checks, migration drift check, tests on Postgres, gitleaks, and a Docker build.
- `AGENTS.md` and `CLAUDE.md` steering docs (Django-native layering, assistant safety rules, coding and testing practices, Conventional Commits and PR conventions) and a PR template.
- Release workflow that publishes versioned images to GHCR after CI passes, with a build-only dry run on PRs that change it. Dependabot for Actions and pip.
- Documentation: architecture, configuration, HTTP API, development and CI/CD, roadmap.
- `manage.py export_tool_reference` generates `docs/tools.md` from the registry; a test fails when the file is stale.
- `requirements.in` with direct dependencies; `requirements.txt` is now a fully pinned uv lock, including previously unpinned transitive packages.

### Changed
- The tuning variables `PLANNER_TIMEOUT`, `PROCESSING_LLM_TIMEOUT`, `PROCESSING_LLM_MAX_TOKENS`, `TOOL_STEP_TIMEOUT`, `PLAN_CACHE_TTL`, `AGENT_THROTTLE_RATE`, `AGENT_MAX_MODIFY_REVISIONS`, and `PLANNER_USAGE_RETENTION_DAYS` are now read from the environment. They were documented before but ignored. Defaults are unchanged.
- Lint covers all pyflakes rules; inherited unused imports were removed.
- GitHub Actions updated to their current major versions (Node 24).

### Fixed
- Test discovery now runs every test (423 at extraction; previously 256). The suite passes on Postgres with exit code 0.
- Garbled characters (mojibake) and UTF-8 BOMs in several tool modules, including the `processing_llm` description shown to the planner.

### Removed
- About 40 unused dependencies (Flask, Supabase client libraries, MCP tooling, and others), plus the unused `SUPABASE_ANON_KEY` setting.
- Supabase login helper, unused prompt/server scripts, dead test helper, the Aiva GHCR image compose file, and the original Aiva docs.
