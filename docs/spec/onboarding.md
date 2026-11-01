# Onboarding: adopting an existing home lab

> **Status: specification.** Nothing here is implemented yet. Goal: someone with a running lab (any number of nodes, their own naming, storage and guests) gets a populated lab state and UI in minutes, without reinstalling anything and without the harness reorganizing their lab.

## Principles

1. **Adopt, don't impose.** The harness learns the lab as it is: node names, storage IDs, bridges, VLANs, VMID ranges, pools and tags. It never renames, moves or "normalizes" anything.
2. **Read-only first.** Discovery uses only read access. The only changes made during onboarding are the harness's own Proxmox user, roles and tokens, plus an optional log collector. The owner sees each change as an exact script or plan and approves it.
3. **Works for 1 to N nodes, clustered or standalone.** It handles a single node, a cluster, several standalone nodes, and mixed versions (each node's version is recorded; recipes check it).
4. **Each part is optional.** Proxmox is required. Linux hosts, Docker hosts, Cloudflare, Obsidian and log collection can each be added later with `hh connect <capability>`.

## The `hh init` flow

```
$ hh init
1. Harness basics      check DB, vault KEK, owner passkey, ntfy topic         (local, no lab changes)
2. Proxmox endpoint    URL of any node; TLS: show cert fingerprint → owner confirms pin
3. Harness identity    print exact pveum script (user harness@pve, roles, privilege-separated
                       tokens per tier, ACLs, agent pool) → owner runs it on one node
                       → paste token secrets into hidden prompts (stored in the vault)
                       (or: --existing-token to reuse a token the owner already has, read tier only)
4. Discovery           read-only sync of cluster, nodes, guests, storage, ZFS, disks, network,
                       firewall, backups → summary: "3 nodes, 27 guests, 5 storages, 2 ZFS pools"
5. Lab profile         propose defaults from what was found (see below) → owner edits/accepts
6. Optional extras     log collector per node (recipe, T2) · Linux/Docker hosts (SSH key generated
                       in the vault, public key + sudoers snippet printed) · Cloudflare · Obsidian
                       · Git mirror of lab documents
7. Verify              `hh doctor`: token scopes exactly as expected, sync fresh, docs render,
                       UI reachable on the tailnet, MCP connection instructions for Claude/Codex
```

- Each step can be re-run (`hh init --step discovery`) and is idempotent.
- A non-interactive mode, `hh init --config lab.toml`, supports scripted installs and the CI nested-PVE suite.
- If the cluster already has a `harness@pve` user, or roles named like ours, init detects them and shows the diff instead of overwriting.

## Lab profile

The lab profile holds the owner's conventions, **inferred from the existing lab** and confirmed by the owner. Recipes use it for defaults so that they work in any lab ([recipes.md](recipes.md#design-rules-so-agents-can-reuse-them) rule 4).

```toml
# lab profile (stored in the DB, editable with `hh lab profile edit`, exported to the Git mirror)
[defaults]
storage_for_disks = "local-zfs"        # inferred: most guest disks live here
storage_for_iso   = "local"
bridge            = "vmbr0"
vmid_range        = [200, 299]         # inferred: unused range above existing guests
agent_pool        = "agent-managed"    # created by the harness identity step
naming            = "{role}-{n}"       # inferred from existing guest names, optional

[templates]                            # discovered templates mapped to OS keys
"ubuntu-24.04" = { vmid = 9000, node = "pve1" }
"debian-13"    = { vmid = 9001, node = "pve1" }

[annotations]                          # owner notes the docs and agents use
"pve3" = "backup node, don't schedule workloads"
"vlan:20" = "IoT"
```

- Every inferred value says why it was inferred ("38 of 41 guest disks are on local-zfs"), and the owner can change it.
- When a recipe needs a default that doesn't exist (for example no template for the requested OS), its preflight says exactly what's missing and offers the recipe that creates it.

## Supported starting points

| Lab | What happens |
|---|---|
| Single node, local storage | Works. Migrate and HA recipes report "not applicable". |
| Cluster with HA and shared storage (Ceph, NFS) | Discovered and documented. Ceph management recipes are a later capability; v1 reads Ceph status only. |
| Multiple standalone nodes, not clustered | Each node is a target. `lab://overview` covers all of them. |
| Mixed PVE versions | Each node's version is recorded. Recipes declare a minimum version and refuse on older nodes. |
| No templates, no backups | Docs and the UI flag these. Recipes are offered to create templates and backup jobs. |
| Existing Cloudflare tunnels and DNS | Adopted read-only. The harness manages only what the owner marks as managed (`hh cloudflare adopt <tunnel>`). |
| Existing Docker stacks | `hh docker adopt <host>` imports the compose projects it finds, so they can be managed from Git ([linux-docker.md](capabilities/linux-docker.md)). |

## Removal

`hh uninstall --lab` prints the exact commands to remove the harness's user, roles, tokens and collectors. Nothing the owner had before is touched. The lab state and Git mirror stay with the owner.

## Tests

- **Fixture-driven discovery** across lab shapes: single node, 3-node HA, standalone pair, mixed versions, no templates.
- **Profile inference**, with explanations, on those fixtures.
- **Init idempotency.** Re-running init produces no change.
- **An existing `harness@pve` user** results in a diff, not an overwrite.
- **The nested-PVE live suite** runs `hh init --config` against a fresh 2-node nested cluster and asserts `hh doctor` is green.
