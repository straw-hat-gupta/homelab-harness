# ADR-0005: Every mutation is a plan, approved out of band, applied as a durable job

- **Status:** accepted (2026-10-31)

## Context

Existing Proxmox MCP servers either expose writes directly, or let the model pass its own approval token. In v0, the LLM classified the owner's "yes" and approved an LLM-written summary, not the resolved action. A home lab has irreversible operations: disk wipes, pool creation, network apply.

## Decision

- Tools are only `read` or `plan_*`. A plan is immutable and hashed. It carries preflight results, a deterministic preview, a risk tier assigned by policy, steps and a rollback note.
- Approval happens only through owner channels: ntfy action, CLI, or UI. It is bound to the plan hash, claimed once, and it expires. T3 additionally requires typed confirmation of the target's identity.
- Applying an approved plan runs preflight again and fails on drift.
- T1 (reversible, inside harness-owned scope) may be auto-approved by policy. It still creates a plan, a job and an audit record.

The full rules are in [safety-model.md](../spec/safety-model.md).

## Consequences

- Every write costs an extra round trip (plan, then approval, then status). Steering teaches models to batch reads and explain previews clearly.
- No MCP client can perform a T2+ action on its own, which is the property the project demonstrates.
