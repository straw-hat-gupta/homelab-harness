# Extending without inheriting a platform

> **Status: binding design discipline; implementation formats remain unselected.** Stage 1 needs a small typed read registry, not a complete plugin/catalog framework.

Before adding anything, search existing active tools/configuration and the relevant [archived source](../code-reuse.md). Use the smallest addition that satisfies the current accepted task. An unimplemented search/catalog command is not a prerequisite to writing the first read tool.

| Need | Smallest appropriate addition |
|---|---|
| Different filter/detail over known facts | Typed query/configuration over the existing source |
| Missing fact | One adapter mapping/read and a bounded view, with source/freshness and failure tests |
| Another task using existing operations | Compose proven primitives rather than copy logic |
| A new runtime | First demonstrate its actual control/auth/tool restrictions; extract shared adapter code only from real duplication |
| Future repeatable write | Typed recipe/steps through the existing plan/approval/verify boundary |
| Future GUI view | Reuse data and a visual template; no frontend-owned policy |
| Future generated tool | Draft outside trusted execution, test, review and owner-install before exposing it |

Inputs are typed and lab-independent: no hard-coded owner node/storage/bridge names. Resolve entity references under the selected instance and authority. Adapters do not import interface code or own policy. New tools declare scope, read/write classification, source/freshness, deadlines/output limits, safe failures and examples. Add tests for success, relevant target errors, canaries and untrusted fields.

A tool cannot register another tool, change permissions, expose a secret or bypass native-runtime restrictions. Reusing a binary/library does not grant it owner authority. A missing operation is refused; raw shell is not a Stage 1 fallback.

Package discovery, decorators, schema formats, SDK extraction, catalog indexing and duplicate-detection automation are later implementation decisions based on actual needs. Do not import them wholesale from the snapshot. [Future intentions](../future.md) preserve reusable widgets/operations without choosing their code structure now.
