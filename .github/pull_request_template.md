<!-- Title: Conventional Commits, e.g. "feat(reminders): parse natural-language reminder times" -->

## Summary
<!-- What changed and why. One concern per PR. -->
-

## Test plan
<!-- Exactly what was run and the result. Check only what you actually ran. -->
- [ ] `python manage.py test` on Postgres: N tests, OK
- [ ] `uvx ruff@0.7.4 check .` clean
- [ ] `python manage.py makemigrations --check --dry-run` no changes
- [ ] New or changed behavior covered by tests (success and important failures)

## Notes
<!-- Follow-ups, risks, anything mocked or not verified against a live provider. Delete if empty. -->
-

## Checklist
- [ ] Docs, `.env.example`, `CHANGELOG.md` (Unreleased), and `docs/tools.md` updated where relevant
- [ ] No secrets, tokens, or personal data in code, tests, fixtures, or logs
