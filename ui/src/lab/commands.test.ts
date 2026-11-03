import { commandEntries } from "@/lab/commands";
import { objectsFromTree } from "@/lab/objects";
import { objectType, tabsFor } from "@/registry";
import { tree } from "@/test/fixtures";

describe("commandEntries", () => {
  const entries = commandEntries(objectsFromTree(tree), objectType, tabsFor);

  it("opens every object, grouped by its type", () => {
    const web = entries.find((e) => e.key === "qemu:home:101");
    expect(web).toMatchObject({
      label: "101 web-01",
      group: "Virtual machines",
      to: { type: "qemu", id: "home:101" },
    });
    expect(web?.keywords).toContain("home:101");
    expect(entries.filter((e) => e.group === "Nodes").map((e) => e.label)).toEqual([
      "pve1",
      "pve2",
    ]);
  });

  it("opens each non-default tab, derived from the tabs registry", () => {
    expect(entries.find((e) => e.key === "node:home:pve1:tasks")).toMatchObject({
      label: "pve1 · Tasks",
      to: { type: "node", id: "home:pve1", tab: "tasks" },
    });
    expect(entries.some((e) => e.key.endsWith(":summary"))).toBe(false);
  });
});
