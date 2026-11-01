# ADR-0006: ntfy for notifications and phone approvals

- **Status:** accepted (2026-10-31)

## Context

Approvals have to reach the owner on their phone quickly. The v0 roadmap planned Twilio SMS, which costs money, needs A2P registration, and has no action buttons. Telegram was also considered.

## Decision

Use self-hosted **ntfy**:
- Messages go to an access-controlled topic.
- They carry action buttons that call the harness approval callback with a signed, single-use token bound to `(plan_hash, decision)`.
- T3 messages carry no one-tap approve button. Their action opens the CLI or UI, where typed confirmation happens.
- Proxmox notification webhooks and harness alerts use the same channel.

## Consequences

- The phone must reach ntfy and the callback, either over the tailnet (the Tailscale app on the phone) or through an Access-protected route.
- Telegram support can be added later as another notifier behind the same interface.
