import type { Unit } from "@/registry/shapes";

const BYTE_UNITS = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"];

/** Bytes in binary units, as the lab documents use them (GiB). */
export function formatBytes(bytes: number): string {
  let value = bytes;
  let unit = 0;
  while (Math.abs(value) >= 1024 && unit < BYTE_UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const digits = unit === 0 || value >= 100 ? 0 : 1;
  return `${value.toFixed(digits)} ${BYTE_UNITS[unit] ?? "B"}`;
}

/** Seconds as the two largest units: `14d 3h`, `2h 5m`, `45s`. */
export function formatDuration(seconds: number): string {
  const parts: [number, string][] = [
    [Math.floor(seconds / 86400), "d"],
    [Math.floor((seconds % 86400) / 3600), "h"],
    [Math.floor((seconds % 3600) / 60), "m"],
    [Math.floor(seconds % 60), "s"],
  ];
  const first = parts.findIndex(([n]) => n > 0);
  if (first === -1) return "0s";
  return parts
    .slice(first, first + 2)
    .filter(([n]) => n > 0)
    .map(([n, u]) => `${n}${u}`)
    .join(" ");
}

/** A value in its unit, or an em dash when unknown. */
export function formatValue(value: number | string | null, unit?: Unit): string {
  if (value === null) return "—";
  if (typeof value === "string") return value;
  switch (unit) {
    case "bytes":
      return formatBytes(value);
    case "seconds":
      return formatDuration(value);
    case "percent":
      return `${value.toFixed(1)} %`;
    case "count":
    case undefined:
      return value.toLocaleString("en");
  }
}

export type Tone = "ok" | "bad" | "neutral";

const OK = new Set(["online", "running", "ok", "active", "available", "quorate"]);
const BAD = new Set(["offline", "unreachable", "failed", "error", "inactive", "no quorum"]);

/** How a status reads at a glance. Unknown statuses are neutral, never alarming. */
export function statusTone(status: string | null | undefined): Tone {
  if (status == null) return "neutral";
  const key = status.toLowerCase();
  if (OK.has(key)) return "ok";
  if (BAD.has(key)) return "bad";
  return "neutral";
}
