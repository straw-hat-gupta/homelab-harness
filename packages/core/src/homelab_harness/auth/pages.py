"""Server-rendered pages for owner login, passkey enrollment and OAuth consent (pure logic).

Minimal HTML with no inline script or style, so the content security policy can
forbid both. Every interpolated value is escaped. The UI (ui.md) will replace
these with its own pages and reuse the same session.
"""

from __future__ import annotations

from html import escape

from homelab_harness.auth.provider import PendingConsent

STATIC_PREFIX = "/owner/static"

SECURITY_HEADERS = {
    # No form-action: the consent form's answer redirects to the client's own
    # redirect URI, which form-action would block in some browsers.
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
        "img-src 'self'; base-uri 'none'; frame-ancestors 'none'"
    ),
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def _page(title: str, body: str, *, ceremony: str = "") -> str:
    script = f'<script src="{STATIC_PREFIX}/webauthn.js" defer></script>' if ceremony else ""
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width,initial-scale=1">'
        f"<title>{escape(title)} · homelab-harness</title>"
        f'<link rel=stylesheet href="{STATIC_PREFIX}/owner.css">{script}</head>'
        f'<body data-ceremony="{escape(ceremony)}"><main><h1>{escape(title)}</h1>'
        f"{body}</main></body></html>"
    )


def login_page(*, next_path: str, error: str | None = None) -> str:
    """The owner login: a passkey button and a recovery-code form."""
    message = f"<p class=error role=alert>{escape(error)}</p>" if error else ""
    nxt = escape(next_path)
    return _page(
        "Owner sign-in",
        f"{message}"
        f'<p><button id=go data-next="{nxt}">Sign in with your passkey</button></p>'
        "<p id=status role=status></p>"
        "<details><summary>Lost your passkey? Use a recovery code</summary>"
        '<form method=post action="/owner/login/recovery">'
        f'<input type=hidden name=next value="{nxt}">'
        "<label>Recovery code <input name=code autocomplete=off required "
        'pattern="[A-Za-z0-9 -]{16,24}" placeholder="XXXX-XXXX-XXXX-XXXX"></label> '
        "<button>Sign in</button></form>"
        "<p>Each code works once. Replace them with "
        "<code>homelab-harness-owner recovery-codes</code> on the harness host.</p></details>",
        ceremony="login",
    )


def enroll_page() -> str:
    """Passkey enrollment; the one-time token is read from the URL fragment by script."""
    return _page(
        "Register the owner's passkey",
        "<p>This link was printed by <code>homelab-harness-owner enroll</code> on the "
        "harness host. It works once and expires after 15 minutes.</p>"
        "<p><button id=go>Register a passkey</button></p><p id=status role=status></p>",
        ceremony="enroll",
    )


def consent_page(pending: PendingConsent, *, csrf: str, access_minutes: int) -> str:
    """The consent screen: who is asking, where the answer goes, and deny by default."""
    kind = (
        "Identified by its metadata document at this URL"
        if pending.kind == "cimd"
        else "Registered itself (dynamic client registration); its name is self-declared"
    )
    warning = (
        "<p class=warning>The answer goes to a program on <strong>this computer</strong> "
        f"({escape(pending.redirect_host)}). Any local program could claim to be this client: "
        "approve only if you started this sign-in yourself, just now.</p>"
        if pending.loopback_redirect
        else ""
    )
    hidden = (
        f'<input type=hidden name=request value="{escape(str(pending.id))}">'
        f'<input type=hidden name=csrf value="{escape(csrf)}">'
    )
    return _page(
        "Allow access to the harness?",
        f"<p><strong>{escape(pending.client_name)}</strong> wants to use the harness's MCP tools "
        "as you.</p><dl>"
        f"<dt>Client</dt><dd><code>{escape(pending.client_id)}</code><br>{escape(kind)}</dd>"
        f"<dt>Sends the answer to</dt><dd><strong>{escape(pending.redirect_host)}</strong> "
        f"(<code>{escape(pending.redirect_uri)}</code>)</dd>"
        f"<dt>Access</dt><dd>{escape(', '.join(pending.scopes))} at "
        f"<code>{escape(pending.resource)}</code>, with {access_minutes}-minute tokens "
        "it can renew until you revoke it (<code>hh clients revoke</code>)</dd></dl>"
        f"{warning}"
        "<p>It cannot approve plans: approvals stay with you.</p>"
        '<div class=actions><form method=post action="/oauth/consent">'
        f"{hidden}<input type=hidden name=decision value=deny>"
        "<button autofocus>Deny</button></form>"
        '<form method=post action="/oauth/consent">'
        f"{hidden}<input type=hidden name=decision value=approve>"
        "<button class=approve>Allow</button></form></div>",
    )


def message_page(title: str, text: str) -> str:
    """A plain message (signed in, link expired, …)."""
    return _page(title, f"<p>{escape(text)}</p>")
