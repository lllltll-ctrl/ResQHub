import { clsx } from "clsx";

interface StatCardProps {
  label: string;
  value: React.ReactNode;
  accent?: "default" | "ok" | "warn" | "crit" | "rescue" | "accent";
  hint?: string;
}

const colorMap: Record<NonNullable<StatCardProps["accent"]>, string> = {
  default: "",
  ok: "border-ok/40",
  warn: "border-warn/40",
  crit: "border-crit/40",
  rescue: "border-rescue/40",
  accent: "border-accent/40",
};

export function StatCard({ label, value, accent = "default", hint }: StatCardProps) {
  return (
    <div className={clsx("card p-4", colorMap[accent])}>
      <div className="label">{label}</div>
      <div className="stat-value mt-1">{value}</div>
      {hint && <div className="text-xs text-text-muted mt-1">{hint}</div>}
    </div>
  );
}