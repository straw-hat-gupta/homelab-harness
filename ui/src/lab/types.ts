/** One object in the lab, as the shell navigates it: a tree node, a page, a palette entry. */
export interface LabObject {
  /** An object type registered in `src/objects/`. */
  type: string;
  /** Stable id, unique across the lab (for example `home:pve1`). */
  id: string;
  /** Display name. Target-sourced (guest names), so rendered as text only. */
  name: string;
  status: string | null;
  /** The parent object's id; `null` for a root. */
  parentId: string | null;
}
