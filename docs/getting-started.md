# Getting started: try Stage 1 on your lab

This guide walks through running what's built so far against a real Proxmox cluster:
- the harness with Postgres, the vault and observability;
- owner passkey login and OAuth;
- the MCP server with 18 read-only Proxmox tools;
- the web UI shell.

Everything is **read-only toward your lab**. The only changes to Proxmox are a service user and tokens, which you create yourself in step 2.

> **Status: first live run.** The code is tested against mocks and fixtures, but no part of it has been verified against a real PVE node, a real browser passkey, or a real Claude Code/Codex login. That's the point of this run. Note what breaks; the [checklist](#what-to-report-back) at the end lists what to look for.

## 0. What you need

- **A Linux host for the harness**, ideally an LXC or VM in the lab, with Docker (Compose v2), Tailscale and Git. The harness must reach a Proxmox node on port 8006.
- **On that host or your workstation:** [uv](https://docs.astral.sh/uv/), for the `hh` CLI and the helper commands.
- **Your workstation** with Claude Code or Codex, on the same tailnet.
- **Optional:** the `pveum` access you'd normally use, as root on one Proxmox node.

```bash
git clone https://github.com/straw-hat-gupta/homelab-harness.git && cd homelab-harness
uv sync
```

## 1. Choose the harness's HTTPS address

Passkeys and OAuth need HTTPS. Tailscale gives the harness host one for free:

```bash
sudo tailscale serve --bg --https=443 http://127.0.0.1:8080
tailscale serve status          # shows https://<host>.<tailnet>.ts.net
export HH_PUBLIC_URL=https://<host>.<tailnet>.ts.net
```

Everything below stays on the tailnet. Don't use `tailscale funnel` or a Cloudflare tunnel yet; the public route is Stage 6.

## 2. Create the harness's Proxmox identity (on one node, as root)

Generate the script on the harness host, read it, then run it on a node:

```bash
uv run python -c "from homelab_harness_proxmox.bootstrap import BootstrapRequest, render_bootstrap_script as r; \
print(r(BootstrapRequest(cluster='home', nodes=['pve1','pve2'])))" > bootstrap.sh   # use your node names
less bootstrap.sh
scp bootstrap.sh root@pve1: && ssh root@pve1 bash bootstrap.sh
```

It creates:
- the user `harness@pve`, which has no password;
- the pool `agent-managed`;
- custom roles;
- three privilege-separated, expiring tokens: `read`, `guest-ops` and `provision`.

**Copy the `value` printed for the `read` token.** Proxmox shows it only once. Stage 1 uses only `read`.

The script's comments mention `hh proxmox token set` and `hh proxmox register`. Those commands don't exist yet, so use steps 4 and 5 instead.

**TLS.** The harness refuses unverified TLS. Pick one option:
- **Pin the certificate fingerprint** (the simplest):
  ```bash
  openssl s_client -connect pve1:8006 </dev/null 2>/dev/null | openssl x509 -noout -fingerprint -sha256
  # → sha256 Fingerprint=AB:CD:…   (use the part after '=')
  ```
- **Or use the cluster CA:** `ssh root@pve1 cat /etc/pve/pve-root-ca.pem > deploy/config/pve-home-ca.pem`

## 3. Start the stack (no targets yet)

```bash
cd deploy
export HH_POSTGRES_PASSWORD="$(openssl rand -hex 24)"          # keep these somewhere safe
export HH_GRAFANA_ADMIN_PASSWORD="$(openssl rand -hex 16)"
export HH_OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
export HH_PUBLIC_URL                                            # from step 1

# Vault key (KEK): owned by the container user (uid 10001), mode 0400, outside the DB.
(umask 077; printf 'kek-1:%s\n' "$(openssl rand -base64 32)" > config/kek)
sudo chown 10001:10001 config/kek && sudo chmod 0400 config/kek
export HH_SECRETS_KEK_PROVIDER=file HH_SECRETS_KEK_FILE=/etc/harness/kek
# Back up config/kek separately: losing it loses every secret.

docker compose --profile observability up -d --build
docker compose ps                     # harness should become healthy
curl -s localhost:8080/readyz         # database, dbos, vault: ok
```

## 4. Owner access: passkey and CLI token

```bash
docker compose exec harness homelab-harness-owner enroll
```

- It prints a **one-time enrollment link** and **10 recovery codes**. Store the codes offline.
- Open the link in the browser you'll use, and register a passkey. Touch ID, Windows Hello or a phone all work.

The CLI uses an owner token. MCP clients never get these.

```bash
(umask 077; docker compose exec -T harness homelab-harness-token create --client hh --role owner > ~/.config/hh-token)
export HH_CLI_TOKEN_FILE=~/.config/hh-token HH_CLI_URL=http://127.0.0.1:8080
uv run hh health
```

## 5. Put the Proxmox token in the vault, then register the cluster

```bash
uv run hh secret add pve-home-read --kind proxmox_token --meta 'token_id=harness@pve!read'   # paste the value; hidden
uv run hh secret show pve-home-read     # metadata only; the value is never shown
```

Create `deploy/config/targets.toml`:

```toml
[[proxmox]]
name = "home"
endpoints = ["pve1.lab.example:8006"]                     # a node the harness host can reach
tls = { kind = "pinned", sha256 = "AB:CD:…" }               # from step 2
# tls = { kind = "ca_bundle", path = "/etc/harness/pve-home-ca.pem" }

[proxmox.credentials.read]
token_id = "harness@pve!read"
token_secret = "secret://pve-home-read"
```

```bash
sudo chown 10001:10001 config/targets.toml
export HH_TARGETS_FILE=/etc/harness/targets.toml
docker compose up -d harness            # restart picks up the targets
curl -s localhost:8080/readyz           # proxmox:home → ok (degraded means it can't read the cluster)
```

## 6. Connect Claude Code or Codex (OAuth)

**Claude Code**, on your workstation:

```bash
claude mcp add --transport http harness "$HH_PUBLIC_URL/mcp"
claude          # then type /mcp → harness → Authenticate
```

**Codex:**

```toml
# ~/.codex/config.toml
[mcp_servers.harness]
url = "https://<host>.<tailnet>.ts.net/mcp"
```

```bash
codex mcp login harness
```

Both open the browser. Log in with your passkey, then approve the consent screen naming the client.

If OAuth fails, you can fall back to a legacy bearer token on the tailnet: create one with `docker compose exec harness homelab-harness-token create --client claude-code`, then add it with `claude mcp add … --header "Authorization: Bearer <token>"`.

## 7. Try it

Ask your client:
- "What nodes are in my cluster and how loaded are they?"
- "List the VMs on pve1 with their status and memory."
- "Show me storage usage and anything over 80%."
- "What disks does pve2 have, and what's their SMART health?"
- "What tasks ran in the last hour, and did any fail?"

Then open:
- **The web UI** at `$HH_PUBLIC_URL`. The side tree shows nodes, guests and storage, and the node pages have Summary and Tasks tabs. If it asks for a token, paste the owner token from `~/.config/hh-token`.
- **Grafana** at `http://127.0.0.1:3000`, or over an SSH tunnel. Log in as `admin` with `$HH_GRAFANA_ADMIN_PASSWORD` and open **Harness overview**. Request traces show up in Tempo, and JSON logs in Loki.
- **The audit trail.** Every MCP tool call is an `mcp.tool_call` event with the client, tool, target and outcome:
  ```bash
  docker compose exec postgres psql -U harness -c "select seq, occurred_at, kind, actor, target from audit_events order by seq desc limit 20"
  ```

## What to report back

| Check | Expected |
|---|---|
| `/readyz` | `proxmox:home` is ok. If it isn't, note the detail text. |
| Tool answers | Real names and numbers, with `as_of` timestamps. Cloud-init passwords and SSH keys are masked or shown as fingerprints. |
| Passkey enrollment and login | Works in your browser. |
| Claude Code `/mcp` authenticate, or `codex mcp login` | Completes, and the consent screen names the client. |
| UI | The tree and node pages load real data, with no console errors. |
| Grafana | The overview panels have data, and traces and logs appear. |
| Logs | `docker compose logs harness \| grep -i -E "token\|secret"` shows no secret values. |
| Anything slow, wrong or confusing | Write it down. It goes into the Stage 2 backlog. |

## Teardown

```bash
docker compose --profile observability down        # keeps data volumes
docker compose --profile observability down -v     # deletes the DB, metrics and logs too
sudo tailscale serve --https=443 off
```

To remove the Proxmox identity, run this on a node: `pveum user delete harness@pve; pveum pool delete agent-managed`, then delete the `Harness*` roles with `pveum role delete`.

## Known gaps (Stage 1)

- Only read tools. Plans, approvals and changes come in Stage 3.
- Reads go to the first endpoint listed. If that node is down, the target reads as `degraded`.
- No lab state or `lab://` documents yet (Stage 2), so the tools call Proxmox directly.
- `hh` uses an owner bearer token, not a device-flow login.
- The UI is a read-only shell, with no actions, logs tab or live updates yet.
- The bootstrap script's comments mention `hh proxmox …` commands that don't exist yet.
