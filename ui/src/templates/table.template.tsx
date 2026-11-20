import { z } from "zod";

import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { defineTemplate } from "@/registry/define";

/** A cell as text. Objects and arrays are shown as JSON, never as markup. */
export function cellText(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

export const template = defineTemplate({
  name: "table",
  summary: "Rows as a table with chosen columns",
  accepts: ["rows"],
  options: z.object({
    caption: z.string().min(1),
    columns: z.array(z.object({ key: z.string().min(1), label: z.string().min(1) })).min(1),
    empty: z.string().default("Nothing to show"),
  }),
  render: ({ data, options }) => (
    <Table>
      <TableCaption className="sr-only">{options.caption}</TableCaption>
      <TableHeader>
        <TableRow>
          {options.columns.map((c) => (
            <TableHead key={c.key}>{c.label}</TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {data.rows.length === 0 ? (
          <TableRow>
            <TableCell colSpan={options.columns.length} className="text-muted-foreground">
              {options.empty}
            </TableCell>
          </TableRow>
        ) : (
          data.rows.map((row, index) => (
            <TableRow key={index}>
              {options.columns.map((c) => (
                <TableCell key={c.key} className="whitespace-normal break-all">
                  {cellText(row[c.key])}
                </TableCell>
              ))}
            </TableRow>
          ))
        )}
      </TableBody>
    </Table>
  ),
});
