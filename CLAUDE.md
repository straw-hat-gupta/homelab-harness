# CLAUDE.md

All project conventions live in AGENTS.md, so every agent follows the same rules:

@AGENTS.md

## Claude Code specifics

- Treat AGENTS.md as binding: the Django-native layering, assistant safety rules, testing, and the Git/PR conventions, including **no "Generated with Claude Code" footer in PR descriptions**.
- Commit trailer: end commit messages with `Co-Authored-By: <model name> <noreply@anthropic.com>`.
- Work on a branch, or in a worktree under `.claude/worktrees/` (gitignored). Never commit to `main` directly.
- Before reporting done, run the checklist at the end of AGENTS.md and quote the actual results (test count, pass/fail).
- When unsure whether an action is automatic or needs confirmation, check the behavior-rules table in `docs/roadmap.md` before writing code.
- Personal, machine-specific notes go in `CLAUDE.local.md` (gitignored), not here.
