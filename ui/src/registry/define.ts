import type { ComponentType, ReactNode } from "react";
import { z } from "zod";

import type { LabObject } from "@/lab/types";
import { SHAPES, type Shape, type ShapeData } from "@/registry/shapes";

/*
 * The UI's extension points (docs/spec/ui.md#extension-points). Each kind has a
 * typed `define*` helper whose manifest is validated with Zod when the module
 * loads, so a malformed extension fails the build's tests, not the owner's page.
 * Files are discovered by `import.meta.glob` in `registry/index.ts`.
 */

const ID = /^[a-z][a-z0-9-]*$/;
const DOTTED = /^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$/;

const component = z.custom<ComponentType<never>>(
  (value) =>
    typeof value === "function" ||
    (typeof value === "object" && value !== null && "$$typeof" in value),
  { message: "must be a React component" },
);

const objectTypes = z.union([z.literal("*"), z.array(z.string().regex(ID)).min(1)]);

// -- object types ------------------------------------------------------------------------

const objectTypeManifest = z.object({
  type: z.string().regex(ID),
  label: z.string().min(1),
  /** Plural label for groups and the palette. */
  plural: z.string().min(1),
  icon: component,
  tree: z.object({
    /** Object types this one hangs under in the side tree; empty for a root. */
    parents: z.array(z.string().regex(ID)),
    /** A folder under the parent ("Storage"), or none to list it directly. */
    group: z.string().min(1).optional(),
    /** Sort order among siblings: lower first. */
    order: z.number().int(),
  }),
  /** The data source that backs the object's page (a catalog id). */
  dataSource: z.string().regex(DOTTED),
});

export type ObjectTypeDefinition = Omit<z.infer<typeof objectTypeManifest>, "icon"> & {
  icon: ComponentType<{ className?: string }>;
};

/** Register an object type: an entity kind with an icon, a tree placement and a data source. */
export function defineObjectType(manifest: ObjectTypeDefinition): ObjectTypeDefinition {
  objectTypeManifest.parse(manifest);
  return manifest;
}

// -- object tabs -------------------------------------------------------------------------

export interface TabProps {
  object: LabObject;
}

const tabManifest = z.object({
  id: z.string().regex(ID),
  label: z.string().min(1),
  /** Position in the tab strip: lower first. */
  order: z.number().int(),
  objectTypes,
  component,
});

export type TabDefinition = Omit<z.infer<typeof tabManifest>, "component"> & {
  component: ComponentType<TabProps>;
};

/** Register a tab on object pages, for some object types or all of them (`"*"`). */
export function defineTab(manifest: TabDefinition): TabDefinition {
  tabManifest.parse(manifest);
  return manifest;
}

// -- actions -----------------------------------------------------------------------------

export interface ActionFormProps {
  object: LabObject;
  /** Hand the prefilled recipe inputs to the plan preview. */
  submit: (inputs: Record<string, unknown>) => void;
}

const actionManifest = z.object({
  id: z.string().regex(ID),
  label: z.string().min(1),
  objectTypes,
  /** The recipe the action plans (docs/spec/recipes.md). Confirmation is its plan preview. */
  recipe: z.string().regex(DOTTED),
  icon: component.optional(),
  /** Only for a custom form; otherwise the form is rendered from the recipe's inputs. */
  form: component.optional(),
});

export type ActionDefinition = Omit<z.infer<typeof actionManifest>, "icon" | "form"> & {
  icon?: ComponentType<{ className?: string }>;
  form?: ComponentType<ActionFormProps>;
};

/**
 * Register a hand-written action. Most actions will be generated from recipe
 * metadata (UI-3); write one only when a recipe needs a custom form.
 */
export function defineAction(manifest: ActionDefinition): ActionDefinition {
  actionManifest.parse(manifest);
  return manifest;
}

// -- widget templates --------------------------------------------------------------------

export type Size = "sm" | "md" | "lg";

export interface TemplateRenderProps<S extends Shape, O> {
  shape: S;
  data: ShapeData[S];
  options: O;
  size: Size;
}

export interface TemplateDefinition<S extends Shape = Shape, O extends z.ZodType = z.ZodType> {
  name: string;
  summary: string;
  accepts: readonly S[];
  /** Options schema: validates widget configs and will render the settings form. */
  options: O;
  render: (props: TemplateRenderProps<S, z.output<O>>) => ReactNode;
}

const templateManifest = z.object({
  name: z.string().regex(ID),
  summary: z.string().min(1),
  accepts: z
    .array(z.enum(SHAPES))
    .min(1)
    .refine((shapes) => new Set(shapes).size === shapes.length, "accepts lists a shape twice"),
  options: z.instanceof(z.ZodType),
  render: z.custom<(...args: never[]) => unknown>((value) => typeof value === "function", {
    message: "must be a function",
  }),
});

/** Register a widget template: a generic component that renders one or more data shapes. */
export function defineTemplate<S extends Shape, O extends z.ZodType>(
  manifest: TemplateDefinition<S, O>,
): TemplateDefinition<S, O> {
  templateManifest.parse(manifest);
  return manifest;
}
