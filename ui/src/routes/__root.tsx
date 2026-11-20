import { createRootRoute, Outlet } from "@tanstack/react-router";

import { SideNav } from "@/components/shell/side-nav";
import { TopBar } from "@/components/shell/top-bar";

export const Route = createRootRoute({
  component: Shell,
  notFoundComponent: () => <p className="text-muted-foreground p-6">This page does not exist.</p>,
});

function Shell() {
  return (
    <div className="flex h-dvh flex-col">
      <TopBar />
      <div className="flex min-h-0 flex-1">
        <aside className="bg-sidebar text-sidebar-foreground w-72 shrink-0 border-r">
          <SideNav />
        </aside>
        <main className="flex min-w-0 flex-1 flex-col overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
