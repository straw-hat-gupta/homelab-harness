# Development: Stage 1A fixture prototype

Python 3.13, the Claude Agent SDK and official MCP SDK are selected only for the current proof. No inference loop, HTTP app, database service, vault or GUI is required. SQLite from the standard library stores private proof metadata. The fresh uv lock includes the official SDK's pinned binary.

```bash
uv sync --frozen --python 3.13
uv run ruff check homelab_harness tests
uv run ruff format --check homelab_harness tests
uv run pyright
uv run pytest -q -W error
uv export --frozen --no-dev --no-emit-project --format requirements-txt --output-file /tmp/hh-requirements.txt --quiet
uv run pip-audit -r /tmp/hh-requirements.txt --disable-pip --no-deps
git diff --check
```

| Location | Owns |
|---|---|
| `homelab_harness/proof.py` | Owner input/login delegation and safe terminal presentation |
| `homelab_harness/runtime.py` | Outer process/session/deadline/output control and pure event validation |
| `homelab_harness/sdk_worker.py` | One concrete SDK adapter and deny-by-default tool policy |
| `homelab_harness/fixture.py` | Fixed stdio MCP schema and invented result |
| `homelab_harness/state.py` | SQLite transactions, registration, audit/budgets and local exclusive lock |
| `tests/` | Fake worker subprocess, actual MCP stdio/SQLite and deterministic policy/failure checks |

The outer controller runs the SDK in a disposable child, so its deadline/output/process-group limits surround both the SDK and its native CLI. The SDK owns the native control protocol; our events are only terminal presentation/session evidence. Hook policy and MCP tool validation are separate gates. `can_use_tool` alone is insufficient because earlier permission steps can approve calls. The all-tool PreToolUse hook is configured to block on callback failure/timeout. The fixture server independently expires; SDK stdio can block in a reader thread, so expiry exits that dedicated process, which must own no unrelated work.

Default tests never call a model account or Proxmox. They prove our policy, real MCP framing and real persistence, not effective Claude or OS isolation. The [guest guide](getting-started.md) is the manual runtime acceptance gate. No historical test count is carried forward.

The archived HTTP CLI/MCP/audit paths were inspected after defining this boundary. Their authenticated HTTP/capability/Postgres layers are unnecessary for one local fixture; no source was copied. Follow [code reuse](code-reuse.md) before adopting future parts. Keep [Stage 1](stage-1.md) gated: do not start Proxmox integration before real 1A evidence.

Documentation checks still cover relative links/headings, tables, entry points, unchanged S1–S10/secrets, archive/legal preservation and whitespace. The code-free inventory was a historical reset check, not a prohibition on this explicitly authorized increment. Record actual results in [validation](validation.md).
