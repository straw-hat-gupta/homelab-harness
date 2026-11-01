# Proxmox API fixtures

`pve-9.2/<endpoint>/<case>.json` holds one response body per file: the full JSON envelope (`{"data": …}` plus top-level keys such as `total` or `changes`).

**These are hand-written from the PVE API viewer documentation. They were not recorded from a live node.** Field names and value encodings (`0`/`1` booleans, `;`-separated tags, epoch times, `"N/A"` wearout) follow the documented schemas. Some fields are marked *(unverified)* in [the spec](../../../../docs/spec/capabilities/proxmox.md), for example `by_id_link` on `disks/list` and the top-level `changes` on `network`.

Values are invented: addresses come from the documentation range `192.0.2.0/24`, serials and digests are made up, and there are no credentials. When the live suite runs against a nested PVE 9.2 cluster, replace or extend these with scrubbed recordings. Keep the same layout, and record the result in `docs/verification.md`.
