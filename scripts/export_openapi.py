"""Write the harness's OpenAPI document, exactly what ``GET /openapi.json`` serves.

The UI generates its API types from it (``pnpm gen:api``). The app is built in
the test environment with no database, targets or UI, so no server, Docker or
network is needed, and the output is deterministic.

Usage: ``python scripts/export_openapi.py <output.json>``
"""

import json
import sys
from pathlib import Path

from homelab_harness.app import create_app
from homelab_harness.settings import Environment, Settings


def main() -> int:
    """Write the document to the path given as the only argument.

    Returns:
        Process exit code.
    """
    if len(sys.argv) != 2:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    out = Path(sys.argv[1])
    out.parent.mkdir(parents=True, exist_ok=True)
    document = create_app(Settings(env=Environment.TEST)).openapi()
    out.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
