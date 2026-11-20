import type { TreeResponse } from "@/api/client";
import type { LabObject } from "@/lab/types";
import type { ObjectTypeDefinition } from "@/registry/define";

/**
 * Flatten the façade's tree into lab objects. Interim: the lab state will serve
 * objects directly; only this function knows the façade's nesting.
 */
export function objectsFromTree(tree: TreeResponse): LabObject[] {
  const objects: LabObject[] = [];
  for (const cluster of tree.clusters) {
    objects.push({
      type: "datacenter",
      id: cluster.id,
      name: cluster.name,
      status: cluster.reachable ? "online" : "unreachable",
      parentId: null,
    });
    for (const node of cluster.nodes) {
      objects.push({
        type: "node",
        id: node.id,
        name: node.name,
        status: node.status,
        parentId: cluster.id,
      });
      for (const guest of node.guests) {
        objects.push({
          type: guest.type,
          id: guest.id,
          name: guest.name ? `${guest.vmid} ${guest.name}` : String(guest.vmid),
          status: guest.template ? "template" : guest.status,
          parentId: node.id,
        });
      }
    }
    for (const storage of cluster.storages) {
      objects.push({
        type: "storage",
        id: storage.id,
        name: `${storage.storage} (${storage.node})`,
        status: storage.status,
        parentId: cluster.id,
      });
    }
  }
  return objects;
}

/** A side-tree entry: an object, or a folder grouping objects of one type. */
export type TreeItem =
  | { kind: "object"; object: LabObject; children: TreeItem[] }
  | { kind: "group"; key: string; label: string; children: TreeItem[] };

/**
 * Arrange objects into the side tree, using each object type's tree placement.
 * Objects whose type is not registered are left out; siblings keep their order
 * within a type and are sorted by the type's `tree.order`.
 */
export function buildTree(
  objects: readonly LabObject[],
  typeOf: (type: string) => ObjectTypeDefinition | undefined,
): TreeItem[] {
  const children = new Map<string | null, LabObject[]>();
  for (const object of objects) {
    if (typeOf(object.type) === undefined) continue;
    const siblings = children.get(object.parentId) ?? [];
    siblings.push(object);
    children.set(object.parentId, siblings);
  }
  const order = (o: LabObject) => typeOf(o.type)?.tree.order ?? 0;

  const level = (parentId: string | null): TreeItem[] => {
    const items: TreeItem[] = [];
    const groups = new Map<string, TreeItem & { kind: "group" }>();
    const sorted = [...(children.get(parentId) ?? [])].sort((a, b) => order(a) - order(b));
    for (const object of sorted) {
      const item: TreeItem = { kind: "object", object, children: level(object.id) };
      const group = typeOf(object.type)?.tree.group;
      if (group === undefined) {
        items.push(item);
        continue;
      }
      let folder = groups.get(group);
      if (folder === undefined) {
        folder = { kind: "group", key: `${parentId ?? ""}/${group}`, label: group, children: [] };
        groups.set(group, folder);
        items.push(folder);
      }
      folder.children.push(item);
    }
    return items;
  };
  return level(null);
}
