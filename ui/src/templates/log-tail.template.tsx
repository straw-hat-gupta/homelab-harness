import { z } from "zod";

import { cn } from "@/lib/utils";
import { defineTemplate } from "@/registry/define";

export const template = defineTemplate({
  name: "log-tail",
  summary: "The last lines of a log, newest at the bottom",
  accepts: ["log-lines"],
  options: z.object({
    label: z.string().min(1),
    maxLines: z.number().int().positive().max(5000).default(200),
    wrap: z.boolean().default(false),
    empty: z.string().default("No log lines"),
  }),
  render: ({ data, options }) => {
    const lines = data.lines.slice(-options.maxLines);
    if (lines.length === 0) {
      return <p className="text-muted-foreground text-sm">{options.empty}</p>;
    }
    return (
      <pre
        role="log"
        aria-label={options.label}
        tabIndex={0}
        className={cn(
          "bg-muted max-h-96 overflow-auto rounded-md p-3 font-mono text-xs leading-5",
          options.wrap ? "whitespace-pre-wrap break-all" : "whitespace-pre",
        )}
      >
        {lines.map((line, index) => (
          <div key={index}>
            {line.ts && <span className="text-muted-foreground">{line.ts} </span>}
            {line.level && <span className="font-semibold">{line.level} </span>}
            {line.text}
          </div>
        ))}
      </pre>
    );
  },
});
