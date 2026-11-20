import { z } from "zod";

/**
 * Data shapes connect data sources to widget templates (docs/spec/catalog.md):
 * a template declares the shapes it accepts, a data source the shape it returns.
 */
export const SHAPES = ["scalar", "rows", "series", "log-lines", "markdown"] as const;
export type Shape = (typeof SHAPES)[number];

export const UNITS = ["percent", "bytes", "seconds", "count"] as const;
export type Unit = (typeof UNITS)[number];

export const shapeSchemas = {
  scalar: z.object({
    value: z.union([z.number(), z.string(), z.null()]),
    unit: z.enum(UNITS).optional(),
    max: z.number().nullable().optional(),
  }),
  rows: z.object({ rows: z.array(z.record(z.string(), z.unknown())) }),
  series: z.object({
    points: z.array(z.object({ t: z.string(), v: z.number().nullable() })),
  }),
  "log-lines": z.object({
    lines: z.array(
      z.object({ ts: z.string().optional(), level: z.string().optional(), text: z.string() }),
    ),
  }),
  markdown: z.object({ markdown: z.string() }),
} satisfies Record<Shape, z.ZodType>;

export interface ShapeData {
  scalar: z.infer<(typeof shapeSchemas)["scalar"]>;
  rows: z.infer<(typeof shapeSchemas)["rows"]>;
  series: z.infer<(typeof shapeSchemas)["series"]>;
  "log-lines": z.infer<(typeof shapeSchemas)["log-lines"]>;
  markdown: z.infer<(typeof shapeSchemas)["markdown"]>;
}

/** Data tagged with its shape, as a widget receives it. */
export type ShapedData = { [S in Shape]: { shape: S; data: ShapeData[S] } }[Shape];
