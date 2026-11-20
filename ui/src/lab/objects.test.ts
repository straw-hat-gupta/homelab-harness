import { buildTree, objectsFromTree, type TreeItem } from "@/lab/objects";
import { objectType } from "@/registry";
import { tree } from "@/test/fixtures";

const names = (items: TreeItem[]): unknown[] =>
  items.map((i) =>
    i.kind === "group"
      ? { group: i.label, children: names(i.children) }
      : i.children.length
        ? { [i.object.name]: names(i.children) }
        : i.object.name,
  );

describe("objectsFromTree", () => {
  it("flattens clusters, nodes, guests and storages with parents", () => {
    const objects = objectsFromTree(tree);
    expect(objects.map((o) => [o.type, o.id, o.parentId])).toEqual([
      ["datacenter", "home", null],
      ["node", "home:pve1", "home"],
      ["qemu", "home:101", "home:pve1"],
      ["qemu", "home:9000", "home:pve1"],
      ["node", "home:pve2", "home"],
      ["lxc", "home:200", "home:pve2"],
      ["storage", "home:pve1:local-zfs", "home"],
    ]);
    expect(objects.find((o) => o.id === "home:9000")?.status).toBe("template");
    expect(objects.find((o) => o.id === "home:101")?.name).toBe("101 web-01");
  });

  it("marks an unreachable cluster", () => {
    const objects = objectsFromTree({
      clusters: tree.clusters.map((c) => ({ ...c, reachable: false, nodes: [], storages: [] })),
    });
    expect(objects).toEqual([
      { type: "datacenter", id: "home", name: "home", status: "unreachable", parentId: null },
    ]);
  });
});

describe("buildTree", () => {
  it("nests by parent, groups storage and orders by the type's tree order", () => {
    expect(names(buildTree(objectsFromTree(tree), objectType))).toEqual([
      {
        home: [
          { pve1: ["101 web-01", "9000 debian-13-tpl"] },
          { pve2: ["200 dns"] },
          { group: "Storage", children: ["local-zfs (pve1)"] },
        ],
      },
    ]);
  });

  it("leaves out objects of unregistered types", () => {
    const objects = [
      ...objectsFromTree(tree),
      { type: "zfs-pool", id: "home:pve1:tank", name: "tank", status: null, parentId: "home:pve1" },
    ];
    expect(JSON.stringify(buildTree(objects, objectType))).not.toContain("tank");
  });
});
