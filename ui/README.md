# Web UI: how to extend it

The UI ([spec](../docs/spec/ui.md)) is built from registries. Files are discovered with
`import.meta.glob`, so you never edit a central list, and core pages use the same registries.
Before adding anything, search what exists ([reuse before create](../AGENTS.md#reuse-before-create-binding)):
`ls src/objects src/tabs src/templates`. Commands: `pnpm dev | lint | typecheck | test | build | e2e | gen:api`.

| Add                       | File                                | Helper             | Export       |
| ------------------------- | ----------------------------------- | ------------------ | ------------ |
| Object type               | `src/objects/<type>.object.ts`      | `defineObjectType` | `objectType` |
| Object tab                | `src/tabs/<id>.tab.tsx`             | `defineTab`        | `tab`        |
| Action (custom form only) | `src/actions/<id>.action.ts`        | `defineAction`     | `action`     |
| Widget template           | `src/templates/<name>.template.tsx` | `defineTemplate`   | `template`   |

Each helper validates its manifest with Zod; `src/registry/registry.test.ts` fails on a bad
manifest or a duplicate id. The command palette is derived from objects and tabs.

## An object type

```ts
export const objectType = defineObjectType({
  type: "zfs-pool",
  label: "ZFS pool",
  plural: "ZFS pools",
  icon: Layers,
  tree: { parents: ["node"], group: "ZFS", order: 30 }, // a "ZFS" folder under each node
  dataSource: "zfs.pool_health", // the catalog data source behind it
});
```

The side tree places objects by `tree`; objects come from the API (`src/lab/objects.ts`).

## A tab

A tab is a component taking `{ object }`, composed of `Section`s holding `Widget`s (a template
name, its options, and data of a shape the template accepts), not bespoke markup. Register it
with `defineTab({ id: "zfs", label: "ZFS", order: 20, objectTypes: ["node"], component })`;
`src/tabs/summary.tab.tsx` is the model to copy.

## A widget template

Only for a genuinely new visual shape. A new view of existing data is a widget **config**.
Templates know nothing about Proxmox: they declare the data shapes they accept
(`scalar`, `rows`, `series`, `log-lines`, `markdown`, see `src/registry/shapes.ts`) and an
options schema. Add a fixture per accepted shape and options in `src/test/fixtures.ts`; the
contract test renders every template with every accepted shape and runs axe on it.

## Actions

UI-1 ships none. From UI-3, actions are generated from recipe metadata; write one by hand only
when a recipe needs a custom form. The confirmation is always the harness plan preview.

## API types

`src/api/schema.gen.ts` is generated from the harness's OpenAPI document: run `pnpm gen:api`
after changing a route or response model, and commit the result (CI checks it). All requests go
through `src/api/client.ts`.
