import { useNavigate } from "@tanstack/react-router";
import { useMemo } from "react";

import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { commandEntries, type CommandEntry } from "@/lab/commands";
import { useLabObjects } from "@/lab/use-objects";
import { objectType, tabsFor } from "@/registry";

/** ⌘K: every object and object tab, derived from the registries. */
export function CommandPalette({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const objects = useLabObjects();
  const navigate = useNavigate();
  const groups = useMemo(() => {
    const byGroup = new Map<string, CommandEntry[]>();
    for (const entry of commandEntries(objects.data ?? [], objectType, tabsFor)) {
      byGroup.set(entry.group, [...(byGroup.get(entry.group) ?? []), entry]);
    }
    return [...byGroup.entries()];
  }, [objects.data]);

  const go = (entry: CommandEntry) => {
    onOpenChange(false);
    void navigate({
      to: "/objects/$type/$id",
      params: { type: entry.to.type, id: entry.to.id },
      search: entry.to.tab ? { tab: entry.to.tab } : {},
    });
  };

  return (
    <CommandDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Search the lab"
      description="Jump to a datacenter, node, guest or storage"
    >
      <Command>
        <CommandInput placeholder="Search objects and tabs…" />
        <CommandList>
          <CommandEmpty>{objects.isPending ? "Loading the lab…" : "No match."}</CommandEmpty>
          {groups.map(([group, entries]) => (
            <CommandGroup key={group} heading={group}>
              {entries.map((entry) => (
                <CommandItem
                  key={entry.key}
                  value={entry.key}
                  keywords={[entry.label, ...entry.keywords]}
                  onSelect={() => {
                    go(entry);
                  }}
                >
                  {entry.label}
                </CommandItem>
              ))}
            </CommandGroup>
          ))}
        </CommandList>
      </Command>
    </CommandDialog>
  );
}
