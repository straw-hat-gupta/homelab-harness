import { statusTone } from "@/lib/format";
import { cn } from "@/lib/utils";

const TONE = {
  ok: "bg-emerald-500",
  bad: "bg-red-500",
  neutral: "bg-muted-foreground/50",
} as const;

/** A coloured dot for a status. Decorative: the status text sits next to it. */
export function StatusDot({ status, className }: { status: string | null; className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-block size-2 shrink-0 rounded-full",
        TONE[statusTone(status)],
        className,
      )}
    />
  );
}
