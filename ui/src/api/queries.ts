import { queryOptions } from "@tanstack/react-query";

import { api, ApiError, type SummaryObjectType } from "@/api/client";

const SUMMARY_TYPES: readonly string[] = ["datacenter", "node", "qemu", "lxc", "storage"];

/** Whether the interim façade can summarize this object type. */
export function hasSummary(type: string): type is SummaryObjectType {
  return SUMMARY_TYPES.includes(type);
}

// A 4xx will not fix itself on retry; a 5xx or a dropped connection might.
const retry = (count: number, error: Error) =>
  !(error instanceof ApiError && error.status < 500) && count < 2;

export const treeQuery = queryOptions({
  queryKey: ["ui", "tree"],
  queryFn: () => api.tree(),
  staleTime: 30_000,
  retry,
});

export function summaryQuery(type: SummaryObjectType, id: string) {
  return queryOptions({
    queryKey: ["ui", "summary", type, id],
    queryFn: () => api.summary(type, id),
    staleTime: 15_000,
    retry,
  });
}
