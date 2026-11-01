"""Fail if a tracked Markdown file links to a relative path that doesn't exist.

External URLs and pure in-page anchors are skipped; only repository-relative
targets are checked, because those break silently when files move.
"""

import re
import subprocess
import sys
from pathlib import Path

LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def main() -> int:
    """Check every tracked Markdown file and report broken relative links.

    Returns:
        Process exit code: 0 when every relative link resolves, 1 otherwise.
    """
    files = subprocess.run(
        ["git", "ls-files", "*.md"], capture_output=True, text=True, check=True
    ).stdout.split()
    broken: list[str] = []
    for name in files:
        path = Path(name)
        in_fence = False
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
            if in_fence:
                continue
            for target in LINK.findall(line):
                if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
                    continue
                resolved = (path.parent / target.split("#", 1)[0]).resolve()
                if not resolved.exists():
                    broken.append(f"{name}:{lineno}: {target}")
    for entry in broken:
        print(f"broken link: {entry}")
    print(f"checked {len(files)} Markdown files, {len(broken)} broken relative links")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
