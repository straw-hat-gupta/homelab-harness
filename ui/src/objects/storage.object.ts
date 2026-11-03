import { Database } from "lucide-react";

import { defineObjectType } from "@/registry/define";

export const objectType = defineObjectType({
  type: "storage",
  label: "Storage",
  plural: "Storage",
  icon: Database,
  tree: { parents: ["datacenter"], group: "Storage", order: 20 },
  dataSource: "ui.objects.summary",
});
