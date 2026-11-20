import { z } from "zod";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatValue } from "@/lib/format";
import { defineTemplate } from "@/registry/define";

export const template = defineTemplate({
  name: "stat",
  summary: "One number with its unit; with a maximum, also a usage bar",
  accepts: ["scalar"],
  options: z.object({ label: z.string().min(1) }),
  render: ({ data, options }) => {
    const { value, unit, max } = data;
    const fraction =
      typeof value === "number" && max != null && max > 0 ? Math.min(value / max, 1) : null;
    const of = max != null && unit !== "percent" ? ` of ${formatValue(max, unit)}` : "";
    return (
      <Card size="sm" className="min-w-0">
        <CardHeader>
          <CardTitle className="text-muted-foreground text-xs font-medium uppercase tracking-wide">
            {options.label}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <p className="text-2xl font-semibold tabular-nums">
            {formatValue(value, unit)}
            {of && <span className="text-muted-foreground text-sm font-normal">{of}</span>}
          </p>
          {fraction !== null && (
            <div
              role="meter"
              aria-label={options.label}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(fraction * 100)}
              className="bg-muted h-1.5 overflow-hidden rounded-full"
            >
              <div
                className="bg-primary h-full rounded-full"
                style={{ width: `${(fraction * 100).toFixed(1)}%` }}
              />
            </div>
          )}
        </CardContent>
      </Card>
    );
  },
});
