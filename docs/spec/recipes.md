# Recipes: reusable, agent-friendly operations

> **Status: specification.** Nothing here is implemented yet. Recipes are how the harness turns "an agent figures out the commands" into "an agent picks a tested operation". They are built on the plan, approve, apply model in [safety-model.md](safety-model.md). Terms follow the [glossary](../../GLOSSARY.md).

## What a recipe is

A **recipe** is a named, versioned, tested operation with typed inputs. Running one produces a plan: preflight, preview, risk tier, steps and rollback. After approval, it runs as a durable job and verifies the result.

Plan tools (`*.plan_*`) in the capability specs are recipes. This document defines the shared contract that makes them reusable by agents.

```
recipe: storage.zfs.create_pool@1.2.0
  summary: Create a ZFS pool from empty disks and register it as Proxmox storage
  inputs:   node: NodeRef, disks: list[DiskRef] (by serial), layout: stripe|mirror|raidz1|raidz2,
            name: PoolName, ashift: int = 12, compression: lz4|zstd = lz4, register_storage: bool = true
  requires: capabilities [proxmox, linux], credentials [proxmox:node-admin, linux:zpool]
  tier:     T3 (floor: wipes disks)
  composes: disk.assert_empty → zfs.create (step) → proxmox.storage.add (recipe) → lab.sync(storage)
  verify:   pool ONLINE with expected vdevs; storage visible on node
  rollback: zpool destroy (irreversible for data written after creation)
  docs:     docs://zfs/layouts, docs://proxmox/storage-zfspool
  examples: 2 disks stripe; 2 disks mirror; 4 disks raidz1
```

## Design rules, so agents can reuse them

1. **Typed inputs, with references instead of free text.** Inputs are pydantic models. Entities are referenced by `NodeRef`, `GuestRef`, `DiskRef`, `StorageRef` and so on, which resolve against the lab state. That means an agent passes `disk:serial:WD-ABC123`, not `/dev/sdb`. Validation errors say exactly which input is wrong and list the valid choices, taken from the lab state.
2. **Small and composable.** A recipe does one thing. Bigger operations **compose** recipes: `cloudflare.expose_service` is made of `cloudflare.access.ensure_app`, then `cloudflare.tunnel.ensure_ingress`, then `cloudflare.dns.ensure_record`. A composite's plan shows every sub-step, gets one approval, and runs as one job.
3. **Idempotent by default.** Recipes are written as "ensure" operations wherever possible (`ensure_*`: create if absent, converge if different, no-op if equal). A no-op plan says so and needs no approval. Steps declare their `RetryClass` ([safety-model.md](safety-model.md) S6).
4. **Lab-agnostic.** Nothing is hard-coded: node names, storage IDs, bridges, VLANs and VMID ranges all come from inputs, the lab state, or the owner's **lab profile** ([onboarding.md](onboarding.md#lab-profile)). Defaults come from the profile (for example `default_storage`, `default_bridge`, `vmid_range`, `template_for(os)`). That's why the same recipe works in any lab.
5. **Self-describing.** Each recipe carries a summary, an input schema, its tier with the reasons, the capabilities and credentials it requires, its composition, verification, rollback, doc links and worked examples. `recipes.describe` returns all of this in about 300 tokens.
6. **Discoverable.** `recipes.search(intent)` searches names, summaries, tags and examples with Postgres full-text search, so it's deterministic and needs no embeddings. Agents search the catalog before considering a raw command ([catalog.md](catalog.md)).
7. **Tested like code.** Each recipe has fixture tests for preflight (including refusals), preview rendering, steps (success, each error class, ambiguity leading to `uncertain`) and verification. Most also have a case in the nested-PVE live suite.
8. **Versioned.** Recipes use semver. Every plan and job records `recipe@version`, so a failure can be traced to the exact recipe code ([observability.md](observability.md#failure-attribution)). A breaking input change bumps the major version.
9. **Steps are shared, not copied.** Low-level steps live in a shared step library per capability (`zfs.create`, `proxmox.task.wait`, `ssh.run_template`, `lab.sync`). A recipe composes steps. A new recipe that needs an existing step imports it, and a contract check flags near-duplicate steps.

## Where recipes live

```
capabilities/<name>/recipes/
  zfs_create_pool.py        # @recipe(...) definition: inputs model, plan builder, steps, verify
  tests/test_zfs_create_pool.py
capabilities/<name>/steps/  # shared step library for that capability
recipes/                    # cross-capability composites (e.g. expose_service, provision_app)
```

`@recipe` is part of the SDK ([extending.md](extending.md)). Core builds the MCP tools from it, so there's no hand-written tool wrapper:
- `recipe.<id>.plan(inputs)` produces a plan.
- `recipes.search`, `recipes.describe` and `recipes.list` are T0.

## Script-style recipes (agent- or owner-authored)

Not everything deserves a Python recipe on day one. A **script recipe** wraps a shell or `pvesh` script so that it's reusable and safe:

```yaml
# recipes/scripts/linux/apt_security_upgrade.yaml
id: linux.apt.security_upgrade
version: 1.0.0
summary: Install pending security updates on a Debian/Ubuntu host or PVE node
inputs:
  host: { type: HostRef }
  reboot_if_required: { type: bool, default: false }
tier: T2                     # policy floors still apply (node reboot → T3)
preflight:
  - check: host.os_family == "debian"
  - run: [apt-get, -s, upgrade]       # dry run; output shown in preview
steps:
  - run: [apt-get, update]
    retry: idempotent
  - run: [unattended-upgrade, -v]
    retry: unsafe
verify:
  - run: [apt-get, -s, upgrade]
    expect: "0 upgraded"
```

Rules:
- Commands are **argv lists with typed placeholders** (`{host}`, `{vmid:int}`). They are never shell strings, and never interpolated by a shell ([linux-docker.md](capabilities/linux-docker.md)).
- They run through the linux capability's SSH executor, using the sudoers allowlist generated from the script recipes that are installed.
- They get the same plan, preview, approval, job and audit path as Python recipes, and the same contract checks: inputs typed, a tier declared, verify present.
- **Promotion path.** When an agent solves something new with a raw command (T3), the steering pack tells it to propose a script recipe capturing that solution, as a PR. The next time it's a tested recipe. This is how the library grows without slop.

## Recipe catalog (initial set, by stage)

| Stage | Recipes |
|---|---|
| 3 | `proxmox.guest.{start,stop,shutdown,reboot,snapshot,rollback,delete_snapshot}`, `proxmox.guest.create_from_template`, `proxmox.guest.clone`, `proxmox.guest.set_resources`, `proxmox.guest.migrate`, `proxmox.guest.destroy`, `proxmox.backup.run_now` |
| 4 | `storage.disk.wipe`, `storage.zfs.create_pool`, `storage.zfs.add_vdev`, `proxmox.storage.add`, `proxmox.network.stage_change`, `proxmox.firewall.ensure_rule`, `linux.apt.security_upgrade`, `linux.systemd.restart`, `docker.stack.deploy`, `docker.stack.rollback`, `observability.install_node_collector` |
| 6 | `cloudflare.expose_service`, `cloudflare.dns.ensure_record`, `cloudflare.access.ensure_app`, `obsidian.task.add` |

## Tests and quality gates

The contract kit, applied to every recipe:
- inputs are typed, with no free-text entity references;
- `describe` stays within budget;
- examples validate against the schema;
- tier ≥ floor;
- verify and rollback are present;
- every step has a retry class;
- no duplicated step (similarity check on step names and argv templates);
- the doc links resolve.
