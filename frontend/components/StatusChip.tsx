import { clsx } from "clsx";
import type { StatusT } from "@/lib/types";

export function StatusChip({ status }: { status: StatusT }) {
  const cls = {
    STABLE: "chip-ok",
    WARNING: "chip-warn",
    CRITICAL: "chip-crit",
    RESCUE_IN_TRANSIT: "chip-rescue",
  }[status];
  const label = {
    STABLE: "Стабільно",
    WARNING: "Увага",
    CRITICAL: "Критично",
    RESCUE_IN_TRANSIT: "Допомога в дорозі",
  }[status];
  return <span className={clsx(cls)}>{label}</span>;
}