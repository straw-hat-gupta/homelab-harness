import createClient, { type Client } from "openapi-fetch";

import type { components, paths } from "@/api/schema.gen";

/*
 * The UI's single data-access module. Every request goes through one typed
 * client generated from the harness's OpenAPI document (`pnpm gen:api`), on
 * the page's own origin.
 */

export type TreeResponse = components["schemas"]["TreeResponse"];
export type TreeCluster = components["schemas"]["TreeCluster"];
export type ObjectSummary = components["schemas"]["ObjectSummary"];
export type SummaryObjectType = components["schemas"]["ObjectType"];

/** An HTTP error with the server's owner-safe `detail`. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const TOKEN_KEY = "hh.ownerToken";

/**
 * The owner token the API calls carry. **Interim** until the passkey session
 * (ADR-0007) replaces it: kept in `sessionStorage`, so it ends with the tab.
 */
export const ownerToken = {
  get(): string | null {
    return sessionStorage.getItem(TOKEN_KEY);
  },
  set(token: string): void {
    sessionStorage.setItem(TOKEN_KEY, token);
  },
  clear(): void {
    sessionStorage.removeItem(TOKEN_KEY);
  },
};

/** Build a client for a harness origin. Tests pass their own `fetch`. */
export function createApi(
  baseUrl: string,
  fetchImpl: typeof fetch = globalThis.fetch,
): Client<paths> {
  const client = createClient<paths>({ baseUrl, fetch: (request) => fetchImpl(request) });
  client.use({
    onRequest({ request }) {
      const token = ownerToken.get();
      if (token) request.headers.set("Authorization", `Bearer ${token}`);
      return request;
    },
  });
  return client;
}

function detailOf(error: unknown): string {
  if (typeof error === "object" && error !== null && "detail" in error) {
    const { detail } = error;
    if (typeof detail === "string") return detail;
  }
  return "the harness could not answer";
}

async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await call;
  if (data === undefined) throw new ApiError(response.status, detailOf(error));
  return data;
}

export interface Api {
  tree(): Promise<TreeResponse>;
  summary(type: SummaryObjectType, id: string): Promise<ObjectSummary>;
}

/** The façade calls the UI makes, over a client. */
export function uiApi(client: Client<paths>): Api {
  return {
    tree: () => unwrap(client.GET("/api/ui/tree")),
    summary: (type, id) =>
      unwrap(
        client.GET("/api/ui/objects/{object_type}/{object_id}/summary", {
          params: { path: { object_type: type, object_id: id } },
        }),
      ),
  };
}

export const api: Api = uiApi(createApi(globalThis.location.origin));
