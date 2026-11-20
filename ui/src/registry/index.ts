import { collect } from "@/registry/collect";
import type {
  ActionDefinition,
  ObjectTypeDefinition,
  TabDefinition,
  TemplateDefinition,
} from "@/registry/define";

/*
 * Every registry is discovered from files: adding an extension never edits a
 * central list. Core object types, tabs and templates are registered the same way.
 */

type Modules = Record<string, Record<string, unknown>>;

const objectModules: Modules = import.meta.glob("../objects/*.object.ts", { eager: true });
const tabModules: Modules = import.meta.glob("../tabs/*.tab.tsx", { eager: true });
const actionModules: Modules = import.meta.glob("../actions/*.action.ts", { eager: true });
const templateModules: Modules = import.meta.glob("../templates/*.template.tsx", {
  eager: true,
});

export const objectTypes: readonly ObjectTypeDefinition[] = collect<ObjectTypeDefinition>(
  objectModules,
  "objectType",
  (o) => o.type,
);

export const tabs: readonly TabDefinition[] = collect<TabDefinition>(
  tabModules,
  "tab",
  (t) => t.id,
).sort((a, b) => a.order - b.order);

export const actions: readonly ActionDefinition[] = collect<ActionDefinition>(
  actionModules,
  "action",
  (a) => a.id,
);

export const templates: readonly TemplateDefinition[] = collect<TemplateDefinition>(
  templateModules,
  "template",
  (t) => t.name,
);

const byType = new Map(objectTypes.map((o) => [o.type, o]));
const byTemplate = new Map(templates.map((t) => [t.name, t]));

const applies = (types: "*" | string[], type: string) => types === "*" || types.includes(type);

/** The registered object type, or `undefined` for one no file registers. */
export function objectType(type: string): ObjectTypeDefinition | undefined {
  return byType.get(type);
}

/** Tabs shown on an object page of this type, in strip order. */
export function tabsFor(type: string): TabDefinition[] {
  return tabs.filter((t) => applies(t.objectTypes, type));
}

/** The registered widget template, or `undefined`. */
export function template(name: string): TemplateDefinition | undefined {
  return byTemplate.get(name);
}
