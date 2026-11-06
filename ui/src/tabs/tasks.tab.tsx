import { Section } from "@/components/section";
import { defineTab, type TabProps } from "@/registry/define";
import { Widget } from "@/widgets/widget";

function TasksTab({ object }: TabProps) {
  return (
    <Section
      title="Tasks"
      description="Task history comes with the lab state (Stage 2): this tab will tail it here."
    >
      <Widget
        config={{
          template: "log-tail",
          options: {
            label: `Tasks of ${object.name}`,
            empty: "No task history yet. It arrives with the lab state.",
          },
        }}
        data={{ shape: "log-lines", data: { lines: [] } }}
      />
    </Section>
  );
}

export const tab = defineTab({
  id: "tasks",
  label: "Tasks",
  order: 50,
  objectTypes: "*",
  component: TasksTab,
});
