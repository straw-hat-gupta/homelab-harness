import { Box } from "lucide-react";

import { defineObjectType } from "@/registry/define";

export const objectType = defineObjectType({
  type: "lxc",
  label: "Container",
  plural: "Containers",
  icon: Box,
  tree: { parents: ["node"], order: 10 },
  dataSource: "ui.objects.summary",
});
