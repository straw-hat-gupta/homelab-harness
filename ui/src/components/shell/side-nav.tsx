import { Link, useParams } from "@tanstack/react-router";
import { ChevronRight, Folder } from "lucide-react";
import { useState } from "react";

import { QueryError } from "@/components/query-state";
import { StatusDot } from "@/components/status-dot";
import { Skeleton } from "@/components/ui/skeleton";
import { buildTree, type TreeItem } from "@/lab/objects";
import { useLabObjects } from "@/lab/use-objects";
import { cn } from "@/lib/utils";
import { objectType } from "@/registry";

function Toggle({ open, label, onClick }: { open: boolean; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-expanded={open}
      aria-label={`${open ? "Collapse" : "Expand"} ${label}`}
      onClick={onClick}
      className="text-muted-foreground hover:text-foreground rounded p-0.5"
    >
      <ChevronRight className={cn("size-3.5 transition-transform", open && "rotate-90")} />
    </button>
  );
}

function Branch({ item, depth, activeId }: { item: TreeItem; depth: number; activeId?: string }) {
  // Datacenters and nodes start open, so a guest is one click away.
  const [open, setOpen] = useState(depth < 2);
  const hasChildren = item.children.length > 0;
  const indent = { paddingLeft: `${depth * 0.75}rem` };
  const label = item.kind === "group" ? item.label : item.object.name;

  let row;
  if (item.kind === "group") {
    row = (
      <div className="flex items-center gap-1.5 py-1" style={indent}>
        <Toggle
          open={open}
          label={label}
          onClick={() => {
            setOpen(!open);
          }}
        />
        <Folder aria-hidden="true" className="text-muted-foreground size-4" />
        <span>{label}</span>
      </div>
    );
  } else {
    const kind = objectType(item.object.type);
    const Icon = kind?.icon;
    row = (
      <div className="flex items-center gap-1.5" style={indent}>
        {hasChildren ? (
          <Toggle
            open={open}
            label={label}
            onClick={() => {
              setOpen(!open);
            }}
          />
        ) : (
          <span className="w-4.5" />
        )}
        <Link
          to="/objects/$type/$id"
          params={{ type: item.object.type, id: item.object.id }}
          aria-current={item.object.id === activeId ? "page" : undefined}
          className={cn(
            "hover:bg-muted flex min-w-0 flex-1 items-center gap-1.5 rounded-md px-1.5 py-1",
            item.object.id === activeId && "bg-muted font-medium",
          )}
        >
          {Icon && <Icon aria-hidden="true" className="text-muted-foreground size-4 shrink-0" />}
          <span className="truncate">{label}</span>
          <StatusDot status={item.object.status} className="ml-auto" />
          <span className="sr-only">{item.object.status ?? "status unknown"}</span>
        </Link>
      </div>
    );
  }
  return (
    <li>
      {row}
      {hasChildren && open && (
        <ul>
          {item.children.map((child) => (
            <Branch
              key={child.kind === "group" ? child.key : child.object.id}
              item={child}
              depth={depth + 1}
              activeId={activeId}
            />
          ))}
        </ul>
      )}
    </li>
  );
}

/** The side tree: datacenters, their nodes and guests, and storage, from the registries. */
export function SideNav() {
  const objects = useLabObjects();
  const params = useParams({ strict: false });
  let body;
  if (objects.isPending) {
    body = (
      <div className="space-y-2 p-2" aria-label="Loading the lab">
        <Skeleton className="h-5 w-3/4" />
        <Skeleton className="h-5 w-2/3" />
        <Skeleton className="h-5 w-1/2" />
      </div>
    );
  } else if (objects.isError) {
    body = (
      <div className="p-2">
        <QueryError error={objects.error} />
      </div>
    );
  } else if (objects.data.length === 0) {
    body = (
      <p className="text-muted-foreground p-2 text-sm">
        No clusters registered. Add one to the targets file (HH_TARGETS_FILE).
      </p>
    );
  } else {
    body = (
      <ul className="text-sm">
        {buildTree(objects.data, objectType).map((item) => (
          <Branch
            key={item.kind === "group" ? item.key : item.object.id}
            item={item}
            depth={0}
            activeId={params.id}
          />
        ))}
      </ul>
    );
  }
  return (
    <nav aria-label="Lab" className="h-full overflow-y-auto p-2">
      {body}
    </nav>
  );
}
