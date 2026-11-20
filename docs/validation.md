# Documentation checkpoint validation

Validated on 2026-11-20 for the reconciliation branch based on `a97f2aacd611f0a6b666f336fda57fad88c27080`. These checks establish the documentation-only tree and its preservation/consistency; they do not establish runtime or cluster capability.

| Check | Result |
|---|---|
| Preserved implementation | Remote `archive/pre-cli-restart-2026-11-20` resolves to the exact base commit; every one of the 296 retired paths matches that preserved tree. |
| Tracked inventory | 48 files: 44 Markdown documents plus LICENSE, NOTICE, .gitignore and .gitattributes. No source, tests, fixtures, locks, deployment/build configuration, assets or executable workflows. |
| File format/mode | All tracked files are non-executable text. |
| Historical/legal preservation | All nine v0 archive documents and LICENSE/NOTICE match the base byte-for-byte. |
| Relative links | 139 repository-relative Markdown links resolve; 0 broken. |
| Heading anchors | All 6 local heading links resolve. |
| Markdown structure | 21 tables in non-v0 documents have consistent columns; link/fence structure checks pass. |
| Safety contract | All ten S1–S10 rows match the previous contract verbatim; accompanying Stage 1 rules prohibit target writes/native-tool bypass and disable automatic approval. |
| Reliability ledger | R-01–R-46 retain their IDs/intent; R-47–R-53 cover runtime isolation/lifecycle. All implementation evidence is explicitly unimplemented, not copied historical coverage. |
| Active-direction review | Runtime owns login/loop/native history; service owns lab tools/context/policy/lifecycle; Mac remains thin. Proposed choices and future intentions are labelled. Old platform blueprints/ADRs remain only in preserved history. |
| Added-document credential scan | No high-risk literal token/private-key matches. Heuristic review only, not a full secret scanner or a guarantee. |
| Whitespace | `git diff --check` / staged equivalent clean. |
| Vendor references | Programmatic Claude CLI/auth conditions and Codex App Server/local-provider docs opened on 2026-11-20. This verifies documentation sources, not an integration. |

Temporary validation tooling ran outside the committed tree. There is intentionally no executable checker or application CI configuration at this checkpoint. External historical links were not exhaustively fetched; relative-link results do not imply external availability.

## Not run or claimed

No runtime integration, model login, paid inference, live-lab operation, deployment, database reset or deletion of owner credentials/untracked work was performed. Application pytest/lint/type checks, frontend/browser checks and container builds are inapplicable because their source/configuration was intentionally retired together. Prior 704-test results belong to the preserved implementation and are not coverage of this checkpoint.

All [Stage 1](stage-1.md) acceptance remains outstanding. When code returns, add the scoped automated checks and separate owner-lab evidence required by that increment.

## Host-availability follow-up, 2026-11-20

Documented the maintainer's required later hosting-node recovery goal in future intentions, roadmap and R-54, with an Unreleased changelog entry. Validation: 48 docs/legal/metadata files; all 142 relative links, 7 local heading anchors and 22 non-v0 tables pass; diff whitespace clean. Stage 1, safety and secrets files are unchanged. Proxmox's HA documentation was consulted for the migration-versus-recovery distinction. No HA, migration, storage, fencing, failure test or live infrastructure change was performed; the requirement is not implemented.
