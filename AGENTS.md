# AGENTS.md

Steering guide for AI coding agents (and humans) working in this repository. Read it before making changes. If anything here conflicts with an explicit instruction from the maintainer, follow the maintainer and suggest an update to this file.

## Project status: rebuild in progress

The v0 Django backend is archived at the `v0-django-final` tag, and its docs are in `docs/archive/v0/`. `main` currently contains documentation only. The rewrite is specified first and then built in stages.

Until the rewrite's own guide replaces this section:
- **Don't restore or extend v0 code on `main`.** Read it at the tag when you need to port logic. Port the logic, not the Django structure.
- **Treat `docs/archive/v0/` as history.** It describes v0 as it was. Don't edit it, except to fix broken links.
- **The v0 audit and its cross-check are input requirements.** Every v0 failure mode they list should become a regression test in the rewrite.

## Documentation

- Docs describe what the code does **now**. Planned work is labelled as planned.
- Add a line under `## [Unreleased]` in `CHANGELOG.md` for user-visible changes.
- Don't claim something works against a real system unless it was verified live. Say "mocked" or "unverified" otherwise.
- No secrets in docs or examples. Use placeholders.

## Git and pull requests

- **Never push to `main`, force-push shared branches, or merge PRs.** The maintainer merges.
- **Branch from the latest `main`**, named `<type>/<short-kebab-description>` (for example `feat/proxmox-tasks`, `docs/threat-model`).
- **Conventional Commits** for commit messages and PR titles: `type(scope): imperative summary`.
  - Types: `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `build`, `ci`, `chore`, `revert`.
  - Scope is the area, e.g. `docs(spec): …`, `feat(proxmox): …`, `ci: …`, `chore(deps): …`.
  - Breaking changes use `!` and a `BREAKING CHANGE:` footer.
- **Commits:**
  - Each one is a coherent, buildable step with a body that explains *why*.
  - Commits written with an AI agent keep a `Co-Authored-By:` trailer naming the model.
  - Don't commit generated junk (`__pycache__`, `.env`, local databases).
- **PRs:**
  - **One concern per PR.**
  - Open it **ready for review**, after running the checks locally.
  - Keep it reviewable; split mechanical changes (renames, formatting) from behavior changes.
  - CI must be green before you ask for review. If CI fails, fix it in a new commit on the branch.
- **PR description** follows [the template](.github/pull_request_template.md):
  - **Summary:** what changed and why.
  - **Test plan:** a checklist of exactly what was run and its result.
  - **Notes:** follow-ups, risks, unverified behavior.
- **Do not add "Generated with Claude Code" or any similar tool-attribution footer to PR descriptions.**
- **Dependabot PRs:** don't hand-edit them; supersede them with a deliberate `chore(deps):` PR when needed.

## Before you say a task is done

1. CI checks pass locally where they can run (currently the secret scan).
2. Links in changed docs resolve.
3. `CHANGELOG.md` is updated where relevant.
4. Report results faithfully. If something failed or was skipped, say so with the output.

## Agent skills

### Issue tracker

Issues live in GitHub Issues for `straw-hat-gupta/agentic-assistant` (gh CLI). See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `GLOSSARY.md` and `docs/adr/`, created lazily. See `docs/agents/domain.md`.
