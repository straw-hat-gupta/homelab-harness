import { useQuery } from "@tanstack/react-query";

import { hasSummary, summaryQuery } from "@/api/queries";
import type { ObjectSummary } from "@/api/client";
import { QueryError } from "@/components/query-state";
import { Section } from "@/components/section";
import { Skeleton } from "@/components/ui/skeleton";
import { defineTab, type TabProps } from "@/registry/define";
import { Widget } from "@/widgets/widget";

/** The Summary tab is configuration over the summary data: stat, status-list and table widgets. */
export function SummaryView({ summary }: { summary: ObjectSummary }) {
  const properties = summary.properties.map((p) => ({
    label: p.label,
    value: p.value,
    source: p.untrusted ? "target (untrusted)" : "harness",
  }));
  return (
    <div className="space-y-4">
      {summary.stats.length > 0 && (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(12rem,1fr))] gap-3">
          {summary.stats.map((stat) => (
            <Widget
              key={stat.key}
              config={{ template: "stat", options: { label: stat.label } }}
              data={{
                shape: "scalar",
                data: { value: stat.value, unit: stat.unit, max: stat.max ?? null },
              }}
            />
          ))}
        </div>
      )}
      {summary.children.length > 0 && (
        <Section title="Members">
          <Widget
            config={{
              template: "status-list",
              options: {
                label: "Members",
                labelField: "name",
                statusField: "status",
                link: { typeField: "type", idField: "id" },
              },
            }}
            data={{ shape: "rows", data: { rows: summary.children } }}
          />
        </Section>
      )}
      <Section
        title="Properties"
        description={`As of ${new Date(summary.as_of).toLocaleString()}. Values marked “target” come from the lab and are shown as text only.`}
      >
        <Widget
          config={{
            template: "table",
            options: {
              caption: "Properties",
              columns: [
                { key: "label", label: "Property" },
                { key: "value", label: "Value" },
                { key: "source", label: "Source" },
              ],
            },
          }}
          data={{ shape: "rows", data: { rows: properties } }}
        />
      </Section>
    </div>
  );
}

function SummaryTab({ object }: TabProps) {
  const type = hasSummary(object.type) ? object.type : null;
  const summary = useQuery({
    ...summaryQuery(type ?? "datacenter", object.id),
    enabled: type !== null,
  });
  if (type === null) {
    return <p className="text-muted-foreground text-sm">No summary for this object type yet.</p>;
  }
  if (summary.isPending) {
    return (
      <div className="grid grid-cols-[repeat(auto-fill,minmax(12rem,1fr))] gap-3">
        <Skeleton className="h-24" />
        <Skeleton className="h-24" />
        <Skeleton className="h-24" />
      </div>
    );
  }
  if (summary.isError) return <QueryError error={summary.error} />;
  return <SummaryView summary={summary.data} />;
}

export const tab = defineTab({
  id: "summary",
  label: "Summary",
  order: 0,
  objectTypes: "*",
  component: SummaryTab,
});
