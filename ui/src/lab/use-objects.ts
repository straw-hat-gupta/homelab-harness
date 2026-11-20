import { useQuery } from "@tanstack/react-query";

import { treeQuery } from "@/api/queries";
import { objectsFromTree } from "@/lab/objects";

/** The lab's objects, from the tree query, shared by the side tree, pages and palette. */
export function useLabObjects() {
  return useQuery({ ...treeQuery, select: objectsFromTree });
}
