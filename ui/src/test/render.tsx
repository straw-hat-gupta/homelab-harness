import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { render } from "@testing-library/react";
import axe from "axe-core";
import type { ReactNode } from "react";

/**
 * Render a component inside a router (with the app's object route, so `Link`s
 * resolve) and a query client preloaded with fixture data. No network.
 */
export async function renderWithApp(
  ui: ReactNode,
  { data = [] }: { data?: [readonly unknown[], unknown][] } = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  for (const [key, value] of data) queryClient.setQueryData(key, value);
  const root = createRootRoute({ component: () => ui });
  const objects = createRoute({ getParentRoute: () => root, path: "/objects/$type/$id" });
  const router = createRouter({
    routeTree: root.addChildren([objects]),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  await router.load();
  const result = render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { ...result, queryClient, router };
}

/** Accessibility violations axe finds in a container (color contrast needs real layout). */
export async function axeViolations(container: Element): Promise<string[]> {
  const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
  return results.violations.map((v) => `${v.id}: ${v.help}`);
}
