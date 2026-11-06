"""Serving the built web UI (``ui/dist``) at ``/`` on the harness's own origin.

- Hashed build output under ``/assets/`` is cached for a year as immutable;
  everything else, ``index.html`` above all, is ``no-cache`` so a deploy is seen
  on the next load.
- Any other path that is not a file falls back to ``index.html``, so client
  routes (``/objects/node/home:pve1``) survive a reload. Paths under the server's
  own prefixes never fall back: an unknown ``/api/...`` stays a JSON 404.
- UI responses carry a strict Content-Security-Policy: same-origin scripts,
  images and requests only, no inline or injected script, no framing. Inline
  styles are allowed (a UI library injects them); they cannot execute code.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse

from homelab_harness_sdk.errors import InvalidInput

CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self'",
        # Radix's scroll lock (dialogs, the palette) injects a <style> element at
        # runtime. Styles cannot run code; scripts stay same-origin only.
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data:",
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    )
)

IMMUTABLE = "public, max-age=31536000, immutable"
NO_CACHE = "no-cache"

# First path segments that belong to the server, never to the SPA: an unknown
# path under them is a 404, not the app shell. ``oauth`` and ``owner`` are the
# authorization server and the owner's passkey pages (homelab_harness.auth).
SERVER_PREFIXES = frozenset(
    {
        "api",
        "mcp",
        "healthz",
        "readyz",
        "docs",
        "redoc",
        "openapi.json",
        ".well-known",
        "oauth",
        "owner",
    }
)

_SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def mount_ui(app: FastAPI, dist: Path) -> None:
    """Serve the UI build from ``dist``. Call after every other route is added.

    Args:
        app: The harness app.
        dist: The Vite build directory (holds ``index.html`` and ``assets/``).

    Raises:
        InvalidInput: If ``dist`` has no ``index.html``.
    """
    root = dist.resolve()
    index = root / "index.html"
    if not index.is_file():
        raise InvalidInput("HH_UI_DIR has no index.html; build the UI first (pnpm build)")

    @app.get("/{path:path}", include_in_schema=False)
    async def ui(path: str) -> FileResponse:  # pyright: ignore[reportUnusedFunction]
        """A file from the build, or ``index.html`` for a client route."""
        segment = path.split("/", 1)[0]
        if segment in SERVER_PREFIXES:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not Found")
        file = _build_file(root, path)
        if file is not None:
            cache = IMMUTABLE if segment == "assets" else NO_CACHE
            return FileResponse(file, headers={**_SECURITY_HEADERS, "Cache-Control": cache})
        if segment == "assets":  # a missing hashed asset is a 404, not the app shell
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not Found")
        return FileResponse(
            index, media_type="text/html", headers={**_SECURITY_HEADERS, "Cache-Control": NO_CACHE}
        )


def _build_file(root: Path, path: str) -> Path | None:
    """The file ``path`` names inside the build, or ``None`` (missing, or outside it)."""
    if not path:
        return None
    candidate = (root / path).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        return None
    return candidate
