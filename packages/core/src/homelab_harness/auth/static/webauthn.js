// Passkey ceremonies for the owner login and enrollment pages (no dependencies).
// The server sends WebAuthn options as JSON with base64url byte fields; the
// browser API wants ArrayBuffers, and its answers go back as base64url again.
"use strict";

(function () {
  const b64urlToBuf = (s) => {
    const pad = "=".repeat((4 - (s.length % 4)) % 4);
    const bin = atob((s + pad).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(bin, (c) => c.charCodeAt(0)).buffer;
  };
  const bufToB64url = (buf) => {
    let bin = "";
    new Uint8Array(buf).forEach((b) => (bin += String.fromCharCode(b)));
    return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  };
  const status = (text) => {
    document.getElementById("status").textContent = text;
  };

  async function post(path, body) {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || "HTTP " + res.status);
    return data;
  }

  function creationOptions(o) {
    o.challenge = b64urlToBuf(o.challenge);
    o.user.id = b64urlToBuf(o.user.id);
    (o.excludeCredentials || []).forEach((c) => (c.id = b64urlToBuf(c.id)));
    return o;
  }

  function requestOptions(o) {
    o.challenge = b64urlToBuf(o.challenge);
    (o.allowCredentials || []).forEach((c) => (c.id = b64urlToBuf(c.id)));
    return o;
  }

  function registrationJSON(cred) {
    return {
      id: cred.id,
      rawId: bufToB64url(cred.rawId),
      type: cred.type,
      response: {
        clientDataJSON: bufToB64url(cred.response.clientDataJSON),
        attestationObject: bufToB64url(cred.response.attestationObject),
        transports: cred.response.getTransports ? cred.response.getTransports() : [],
      },
      clientExtensionResults: cred.getClientExtensionResults(),
      authenticatorAttachment: cred.authenticatorAttachment,
    };
  }

  function assertionJSON(cred) {
    const r = cred.response;
    return {
      id: cred.id,
      rawId: bufToB64url(cred.rawId),
      type: cred.type,
      response: {
        clientDataJSON: bufToB64url(r.clientDataJSON),
        authenticatorData: bufToB64url(r.authenticatorData),
        signature: bufToB64url(r.signature),
        userHandle: r.userHandle ? bufToB64url(r.userHandle) : null,
      },
      clientExtensionResults: cred.getClientExtensionResults(),
      authenticatorAttachment: cred.authenticatorAttachment,
    };
  }

  async function login(next) {
    const start = await post("/owner/login/options", {});
    const cred = await navigator.credentials.get({ publicKey: requestOptions(start.options) });
    const done = await post("/owner/login/verify", {
      challenge_id: start.challenge_id,
      credential: assertionJSON(cred),
      next: next,
    });
    window.location.assign(done.redirect);
  }

  async function enroll() {
    const token = new URLSearchParams(window.location.hash.slice(1)).get("token") || "";
    // Drop the token from the address bar and history once read.
    history.replaceState(null, "", window.location.pathname);
    const start = await post("/owner/enroll/options", { token: token });
    const cred = await navigator.credentials.create({ publicKey: creationOptions(start.options) });
    const done = await post("/owner/enroll/verify", {
      token: token,
      challenge_id: start.challenge_id,
      credential: registrationJSON(cred),
    });
    window.location.assign(done.redirect);
  }

  document.addEventListener("DOMContentLoaded", () => {
    const button = document.getElementById("go");
    if (!button) return;
    if (!window.PublicKeyCredential) {
      status("This browser does not support passkeys here (it needs HTTPS or localhost).");
      button.disabled = true;
      return;
    }
    button.addEventListener("click", async () => {
      button.disabled = true;
      status("Waiting for your passkey…");
      try {
        if (document.body.dataset.ceremony === "enroll") await enroll();
        else await login(button.dataset.next || "/owner/login");
      } catch (err) {
        status(err && err.message ? err.message : "That did not work; try again.");
        button.disabled = false;
      }
    });
  });
})();
