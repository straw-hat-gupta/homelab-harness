import type { ObjectSummary, TreeResponse } from "@/api/client";
import type { ShapedData, Shape } from "@/registry/shapes";

/*
 * A fixture lab: shared by the unit tests and the Playwright smoke test, which
 * serves it in place of the harness API. Values are invented.
 */

export const tree: TreeResponse = {
  clusters: [
    {
      id: "home",
      name: "home",
      reachable: true,
      error: null,
      as_of: "2026-11-01T12:00:00Z",
      nodes: [
        {
          id: "home:pve1",
          name: "pve1",
          status: "online",
          guests: [
            {
              id: "home:101",
              vmid: 101,
              type: "qemu",
              name: "web-01",
              status: "running",
              template: false,
            },
            {
              id: "home:9000",
              vmid: 9000,
              type: "qemu",
              name: "debian-13-tpl",
              status: "stopped",
              template: true,
            },
          ],
        },
        {
          id: "home:pve2",
          name: "pve2",
          status: null,
          guests: [
            {
              id: "home:200",
              vmid: 200,
              type: "lxc",
              name: "dns",
              status: "stopped",
              template: false,
            },
          ],
        },
      ],
      storages: [
        { id: "home:pve1:local-zfs", storage: "local-zfs", node: "pve1", status: "available" },
      ],
    },
  ],
};

export const nodeSummary: ObjectSummary = {
  type: "node",
  id: "home:pve1",
  title: "pve1",
  status: null,
  as_of: "2026-11-01T12:00:00Z",
  stats: [
    { key: "cpu", label: "CPU", value: 8, max: 100, unit: "percent" },
    { key: "memory", label: "Memory", value: 17179869184, max: 68719476736, unit: "bytes" },
    { key: "uptime", label: "Uptime", value: 1209600, max: null, unit: "seconds" },
  ],
  properties: [
    { label: "CPU model", value: "AMD Ryzen 9 7950X", untrusted: false },
    { label: "Kernel", value: "Linux 7.0.4-1-pve", untrusted: false },
  ],
  children: [],
};

export const datacenterSummary: ObjectSummary = {
  type: "datacenter",
  id: "home",
  title: "home",
  status: "quorate",
  as_of: "2026-11-01T12:00:00Z",
  stats: [{ key: "nodes_online", label: "Nodes online", value: 1, max: 2, unit: "count" }],
  properties: [{ label: "PVE version", value: "9.2.1", untrusted: false }],
  children: [
    { type: "node", id: "home:pve1", name: "pve1", status: "online" },
    { type: "node", id: "home:pve2", name: "pve2", status: "offline" },
  ],
};

export const guestSummary: ObjectSummary = {
  type: "qemu",
  id: "home:101",
  title: "101 (web-01)",
  status: "running",
  as_of: "2026-11-01T12:00:00Z",
  stats: [{ key: "cpu", label: "CPU", value: 50, max: 100, unit: "percent" }],
  properties: [
    { label: "Name", value: "web-01", untrusted: true },
    { label: "config: cipassword", value: "[MASKED]", untrusted: true },
  ],
  children: [],
};

/** One fixture per data shape, for the template contract tests. */
export const shapeFixtures: { [S in Shape]: Extract<ShapedData, { shape: S }> } = {
  scalar: { shape: "scalar", data: { value: 1073741824, unit: "bytes", max: 4294967296 } },
  rows: {
    shape: "rows",
    data: {
      rows: [
        { name: "pve1", status: "online", type: "node", id: "home:pve1" },
        { name: "pve2", status: "offline", type: "node", id: "home:pve2" },
      ],
    },
  },
  series: { shape: "series", data: { points: [{ t: "2026-11-01T12:00:00Z", v: 1 }] } },
  "log-lines": {
    shape: "log-lines",
    data: {
      lines: [
        { ts: "12:00:00", level: "INFO", text: "starting vzdump" },
        { ts: "12:00:05", text: "finished" },
      ],
    },
  },
  markdown: { shape: "markdown", data: { markdown: "# pve1\n\n- **load** 0.42" } },
};

/** Options that make each shipped template render its fixture. */
export const templateOptions: Record<string, unknown> = {
  stat: { label: "Memory" },
  table: {
    caption: "Nodes",
    columns: [
      { key: "name", label: "Name" },
      { key: "status", label: "Status" },
    ],
  },
  "status-list": { label: "Nodes", labelField: "name", statusField: "status" },
  markdown: {},
  "log-tail": { label: "Task log" },
};
