import { Server } from "lucide-react";

import { defineObjectType } from "@/registry/define";

export const objectType = defineObjectType({
  type: "node",
  label: "Node",
  plural: "Nodes",
  icon: Server,
  tree: { parents: ["datacenter"], order: 10 },
  dataSource: "ui.objects.summary",
});
