import { createFileRoute } from "@tanstack/react-router";

import { QueryError } from "@/components/query-state";
import { Section } from "@/components/section";
import { useLabObjects } from "@/lab/use-objects";
import { Widget } from "@/widgets/widget";

export const Route = createFileRoute("/")({ component: Home });

function Home() {
  const objects = useLabObjects();
  const datacenters = (objects.data ?? []).filter((o) => o.parentId === null);
  return (
    <div className="space-y-4 p-6">
      <h1 className="text-xl font-semibold">Lab</h1>
      <Section title="Datacenters" description="Every registered cluster. Pick one to start.">
        {objects.isError ? (
          <QueryError error={objects.error} />
        ) : (
          <Widget
            config={{
              template: "status-list",
              options: {
                label: "Datacenters",
                labelField: "name",
                statusField: "status",
                link: { typeField: "type", idField: "id" },
                empty: objects.isPending ? "Loading the lab…" : "No clusters registered.",
              },
            }}
            data={{ shape: "rows", data: { rows: datacenters.map((o) => ({ ...o })) } }}
          />
        )}
      </Section>
    </div>
  );
}
