import { Server } from "lucide-react";
import { z } from "zod";

import { actions, objectType, objectTypes, tabs, tabsFor, template, templates } from "@/registry";
import { collect } from "@/registry/collect";
import { defineAction, defineObjectType, defineTab, defineTemplate } from "@/registry/define";
import { SHAPES } from "@/registry/shapes";

describe("discovered registries (contract)", () => {
  it("registers the core object types, tabs and templates from files", () => {
    expect(objectTypes.map((o) => o.type).sort()).toEqual([
      "datacenter",
      "lxc",
      "node",
      "qemu",
      "storage",
    ]);
    expect(tabs.map((t) => t.id)).toEqual(["summary", "tasks"]);
    expect(templates.map((t) => t.name).sort()).toEqual([
      "log-tail",
      "markdown",
      "stat",
      "status-list",
      "table",
    ]);
    // UI-1 ships no actions: they are generated from recipes from UI-3 on.
    expect(actions).toEqual([]);
  });

  it("places every object type under registered parents", () => {
    const known = new Set(objectTypes.map((o) => o.type));
    for (const o of objectTypes) {
      for (const parent of o.tree.parents) expect(known).toContain(parent);
    }
    expect(objectTypes.filter((o) => o.tree.parents.length === 0).map((o) => o.type)).toEqual([
      "datacenter",
    ]);
  });

  it("scopes tabs to existing object types and gives every type a Summary first", () => {
    const known = new Set(objectTypes.map((o) => o.type));
    for (const t of tabs) {
      if (t.objectTypes !== "*") for (const type of t.objectTypes) expect(known).toContain(type);
    }
    for (const o of objectTypes) expect(tabsFor(o.type)[0]?.id).toBe("summary");
  });

  it("accepts only known shapes in templates", () => {
    for (const t of templates) {
      for (const shape of t.accepts) expect(SHAPES).toContain(shape);
    }
    expect(template("stat")?.accepts).toEqual(["scalar"]);
    expect(template("nope")).toBeUndefined();
    expect(objectType("nope")).toBeUndefined();
  });
});

describe("collect", () => {
  const node = { type: "node" };

  it("orders entries by path", () => {
    const entries = collect<{ type: string }>(
      { "./b.ts": { objectType: { type: "b" } }, "./a.ts": { objectType: { type: "a" } } },
      "objectType",
      (o) => o.type,
    );
    expect(entries.map((e) => e.type)).toEqual(["a", "b"]);
  });

  it("rejects a file without the export", () => {
    expect(() => collect({ "./x.ts": { other: node } }, "objectType", () => "x")).toThrow(
      "./x.ts must export `objectType`",
    );
  });

  it("rejects an id registered twice", () => {
    expect(() =>
      collect<{ type: string }>(
        { "./a.ts": { objectType: node }, "./b.ts": { objectType: node } },
        "objectType",
        (o) => o.type,
      ),
    ).toThrow('./b.ts registers "node", already registered by ./a.ts');
  });
});

describe("define helpers validate manifests", () => {
  const Tab = () => null;

  it("rejects a malformed object type", () => {
    expect(() =>
      defineObjectType({
        type: "Not Kebab",
        label: "x",
        plural: "x",
        icon: Server,
        tree: { parents: [], order: 0 },
        dataSource: "ui.objects.summary",
      }),
    ).toThrow();
    expect(() =>
      defineObjectType({
        type: "zfs-pool",
        label: "ZFS pool",
        plural: "ZFS pools",
        icon: Server,
        tree: { parents: ["node"], order: 0 },
        dataSource: "not dotted",
      }),
    ).toThrow();
  });

  it("rejects a tab with no object types", () => {
    expect(() =>
      defineTab({ id: "zfs", label: "ZFS", order: 1, objectTypes: [], component: Tab }),
    ).toThrow();
    expect(
      defineTab({ id: "zfs", label: "ZFS", order: 1, objectTypes: ["node"], component: Tab }).id,
    ).toBe("zfs");
  });

  it("rejects an action that names no recipe", () => {
    expect(() =>
      defineAction({ id: "snapshot", label: "Snapshot", objectTypes: ["qemu"], recipe: "" }),
    ).toThrow();
    expect(
      defineAction({
        id: "snapshot",
        label: "Snapshot",
        objectTypes: ["qemu", "lxc"],
        recipe: "proxmox.guest.snapshot",
      }).recipe,
    ).toBe("proxmox.guest.snapshot");
  });

  it("rejects a template with an unknown or repeated shape", () => {
    const base = { name: "gauge", summary: "A dial", options: z.object({}), render: () => null };
    expect(() => defineTemplate({ ...base, accepts: ["scalar", "scalar"] })).toThrow();
    // @ts-expect-error -- "topology" is not a shape
    expect(() => defineTemplate({ ...base, accepts: ["topology"] })).toThrow();
    expect(defineTemplate({ ...base, accepts: ["scalar"] }).name).toBe("gauge");
  });
});
