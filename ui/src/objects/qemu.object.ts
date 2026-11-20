import { Monitor } from "lucide-react";

import { defineObjectType } from "@/registry/define";

export const objectType = defineObjectType({
  type: "qemu",
  label: "Virtual machine",
  plural: "Virtual machines",
  icon: Monitor,
  tree: { parents: ["node"], order: 10 },
  dataSource: "ui.objects.summary",
});
