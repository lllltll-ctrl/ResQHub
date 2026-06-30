"use client";

import type { StatusT } from "@/lib/types";

const STYLE: Record<StatusT, string> = {
  STABLE: "chip-stable",
  WARNING: "chip-warning",
  CRITICAL: "chip-critical",
  RESCUE_IN_TRANSIT: "chip-rescue",
};

const LABEL: Record<StatusT, string> = {
  STABLE: "Стабіль",
  WARNING: "Увага",
  CRITICAL: "Крит.",
  RESCUE_IN_TRANSIT: "Доп. їде",
};

export function StatusPill({
  status,
  size = "md",
}: {
  status: StatusT;
  size?: "sm" | "md";
}) {
  const sizeClass =
    size === "sm" ? "text-[10px] px-2 py-0.5" : "text-[11px] px-2 py-0.5";
  return (
    <span
      className={`inline-flex items-center rounded font-bold tracking-wider uppercase ${STYLE[status]} ${sizeClass}`}
    >
      {LABEL[status]}
    </span>
  );
}
