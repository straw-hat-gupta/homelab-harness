import { template as lookup } from "@/registry";
import type { Size, TemplateDefinition } from "@/registry/define";
import { shapeSchemas, type ShapedData } from "@/registry/shapes";

/** A widget is configuration: a template, its options, and data of a shape it accepts. */
export interface WidgetConfig {
  template: string;
  options?: unknown;
}

function Problem({ children }: { children: string }) {
  return (
    <p role="alert" className="text-destructive rounded-md border border-dashed p-3 text-sm">
      {children}
    </p>
  );
}

/**
 * Render one widget, checking its config before any template code runs: the
 * template must exist and accept the data's shape, and the options and data
 * must match their schemas. A bad config shows as a problem, not a crash.
 */
export function Widget({
  config,
  data,
  size = "md",
}: {
  config: WidgetConfig;
  data: ShapedData;
  size?: Size;
}) {
  const found: TemplateDefinition | undefined = lookup(config.template);
  if (found === undefined)
    return <Problem>{`Unknown widget template "${config.template}"`}</Problem>;
  if (!found.accepts.includes(data.shape)) {
    return <Problem>{`Template "${found.name}" does not accept ${data.shape} data`}</Problem>;
  }
  const options = found.options.safeParse(config.options ?? {});
  if (!options.success) return <Problem>{`Invalid options for "${found.name}"`}</Problem>;
  const shaped = shapeSchemas[data.shape].safeParse(data.data);
  if (!shaped.success) return <Problem>{`Data does not match the ${data.shape} shape`}</Problem>;
  return found.render({ shape: data.shape, data: data.data, options: options.data, size });
}
