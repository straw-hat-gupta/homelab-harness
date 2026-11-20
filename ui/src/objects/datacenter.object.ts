import { Building2 } from "lucide-react";

import { defineObjectType } from "@/registry/define";

export const objectType = defineObjectType({
  type: "datacenter",
  label: "Datacenter",
  plural: "Datacenters",
  icon: Building2,
  tree: { parents: [], order: 0 },
  dataSource: "ui.objects.summary",
});
