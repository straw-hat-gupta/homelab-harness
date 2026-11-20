import type { LabObject } from "@/lab/types";
import type { ObjectTypeDefinition, TabDefinition } from "@/registry/define";

/** A command palette entry: where it goes and what it is found by. */
export interface CommandEntry {
  key: string;
  label: string;
  group: string;
  keywords: string[];
  to: { type: string; id: string; tab?: string };
}

/**
 * Derive the palette from the registries: open each object, and open each of
 * its non-default tabs ("Open pve1 · Tasks"). Nothing is registered by hand.
 * Actions join when they can run (UI-3).
 *
 * @param objects - The lab's objects.
 * @param typeOf - Object type lookup (the registry).
 * @param tabsFor - Tabs of an object type, in strip order (the registry).
 */
export function commandEntries(
  objects: readonly LabObject[],
  typeOf: (type: string) => ObjectTypeDefinition | undefined,
  tabsFor: (type: string) => TabDefinition[],
): CommandEntry[] {
  const entries: CommandEntry[] = [];
  for (const object of objects) {
    const kind = typeOf(object.type);
    if (kind === undefined) continue;
    const keywords = [object.id, kind.label, object.type];
    entries.push({
      key: `${object.type}:${object.id}`,
      label: object.name,
      group: kind.plural,
      keywords,
      to: { type: object.type, id: object.id },
    });
    for (const tab of tabsFor(object.type).slice(1)) {
      entries.push({
        key: `${object.type}:${object.id}:${tab.id}`,
        label: `${object.name} · ${tab.label}`,
        group: "Tabs",
        keywords: [...keywords, tab.id],
        to: { type: object.type, id: object.id, tab: tab.id },
      });
    }
  }
  return entries;
}
