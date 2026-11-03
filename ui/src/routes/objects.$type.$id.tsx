import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { ObjectPage } from "@/components/shell/object-page";

const search = z.object({ tab: z.string().optional() });

export const Route = createFileRoute("/objects/$type/$id")({
  validateSearch: search,
  component: ObjectRoute,
});

function ObjectRoute() {
  const { type, id } = Route.useParams();
  const { tab } = Route.useSearch();
  // Keyed by object, so per-object state (open sections, the tab) resets on navigation.
  return <ObjectPage key={`${type}:${id}`} type={type} id={id} tab={tab} />;
}
