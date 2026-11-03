import { Link } from "@tanstack/react-router";
import { z } from "zod";

import { StatusDot } from "@/components/status-dot";
import { defineTemplate } from "@/registry/define";

const text = (value: unknown): string | null =>
  typeof value === "string" || typeof value === "number" ? String(value) : null;

export const template = defineTemplate({
  name: "status-list",
  summary: "Rows as a list of labels with a status each, optionally linking to object pages",
  accepts: ["rows"],
  options: z.object({
    label: z.string().min(1),
    labelField: z.string().min(1),
    statusField: z.string().min(1),
    /** Row fields holding an object's type and id, to link each row to its page. */
    link: z.object({ typeField: z.string().min(1), idField: z.string().min(1) }).optional(),
    empty: z.string().default("Nothing to show"),
  }),
  render: ({ data, options }) => {
    if (data.rows.length === 0) {
      return <p className="text-muted-foreground text-sm">{options.empty}</p>;
    }
    return (
      <ul aria-label={options.label} className="divide-border divide-y text-sm">
        {data.rows.map((row, index) => {
          const label = text(row[options.labelField]) ?? "—";
          const status = text(row[options.statusField]);
          const type = options.link && text(row[options.link.typeField]);
          const id = options.link && text(row[options.link.idField]);
          const body = (
            <>
              <StatusDot status={status} />
              <span className="min-w-0 flex-1 truncate">{label}</span>
              <span className="text-muted-foreground">{status ?? "unknown"}</span>
            </>
          );
          return (
            <li key={index}>
              {type && id ? (
                <Link
                  to="/objects/$type/$id"
                  params={{ type, id }}
                  className="hover:bg-muted flex items-center gap-2 rounded-md px-2 py-1.5"
                >
                  {body}
                </Link>
              ) : (
                <div className="flex items-center gap-2 px-2 py-1.5">{body}</div>
              )}
            </li>
          );
        })}
      </ul>
    );
  },
});
