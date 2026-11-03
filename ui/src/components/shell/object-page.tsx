import { useNavigate } from "@tanstack/react-router";

import { StatusDot } from "@/components/status-dot";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { LabObject } from "@/lab/types";
import { useLabObjects } from "@/lab/use-objects";
import { objectType, tabsFor } from "@/registry";

/** An object's page: its header and a tab strip contributed by the tabs registry. */
export function ObjectPage({ type, id, tab }: { type: string; id: string; tab?: string }) {
  const navigate = useNavigate();
  const objects = useLabObjects();
  const kind = objectType(type);
  if (kind === undefined) {
    return <p className="text-muted-foreground p-6">No object type “{type}” is registered.</p>;
  }
  // The page works before (or without) the tree: the id is a fine fallback name.
  const object: LabObject = objects.data?.find((o) => o.type === type && o.id === id) ?? {
    type,
    id,
    name: id,
    status: null,
    parentId: null,
  };
  const strip = tabsFor(type);
  const active = strip.find((t) => t.id === tab) ?? strip[0];
  const Icon = kind.icon;

  return (
    <article className="flex min-h-0 flex-1 flex-col gap-4 p-6">
      <header className="flex items-center gap-3">
        <Icon aria-hidden="true" className="text-muted-foreground size-6" />
        <div className="min-w-0">
          <h1 className="truncate text-xl font-semibold">{object.name}</h1>
          <p className="text-muted-foreground flex items-center gap-1.5 text-sm">
            {kind.label}
            {object.status && (
              <>
                <span aria-hidden="true">·</span>
                <StatusDot status={object.status} />
                {object.status}
              </>
            )}
          </p>
        </div>
      </header>
      {active && (
        <Tabs
          value={active.id}
          onValueChange={(value) => {
            void navigate({
              to: "/objects/$type/$id",
              params: { type, id },
              search: { tab: value },
            });
          }}
        >
          <TabsList variant="line">
            {strip.map((t) => (
              <TabsTrigger key={t.id} value={t.id}>
                {t.label}
              </TabsTrigger>
            ))}
          </TabsList>
          {strip.map((t) => (
            <TabsContent key={t.id} value={t.id} className="pt-4">
              <t.component object={object} />
            </TabsContent>
          ))}
        </Tabs>
      )}
    </article>
  );
}
