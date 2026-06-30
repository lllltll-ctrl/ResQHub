"use client";

import { useMemo, useState } from "react";
import { clsx } from "clsx";
import type { ObjectState, StatusT } from "@/lib/types";
import { OBJECT_TYPE_UA } from "@/lib/types";
import { ScoreRing } from "./ScoreRing";

type Filter = "all" | StatusT;

interface ObjectListProps {
  objects: ObjectState[];
  selectedId?: string | null;
  onSelect?: (id: string) => void;
}

export function ObjectList({ objects, selectedId, onSelect }: ObjectListProps) {
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    let out = objects;
    if (filter !== "all") {
      out = out.filter((o) => (o.score?.status ?? "STABLE") === filter);
    }
    if (query.trim()) {
      const q = query.toLowerCase();
      out = out.filter(
        (o) =>
          o.name.toLowerCase().includes(q) ||
          o.district.toLowerCase().includes(q),
      );
    }
    // Сортування: критичні спочатку, потім warning, потім stable
    const rank: Record<StatusT, number> = {
      CRITICAL: 0,
      WARNING: 1,
      RESCUE_IN_TRANSIT: 2,
      STABLE: 3,
    };
    return [...out].sort(
      (a, b) =>
        rank[(a.score?.status ?? "STABLE") as StatusT] -
        rank[(b.score?.status ?? "STABLE") as StatusT],
    );
  }, [objects, filter, query]);

  const filters: { label: string; value: Filter }[] = [
    { label: "Всі", value: "all" },
    { label: "Стабільні", value: "STABLE" },
    { label: "Увага", value: "WARNING" },
    { label: "Критичні", value: "CRITICAL" },
    { label: "Допомога", value: "RESCUE_IN_TRANSIT" },
  ];

  return (
    <div className="panel flex flex-col h-full">
      <div className="p-3 border-b border-border">
        <input
          type="text"
          placeholder="Пошук об'єкта..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-full bg-bg-card border border-border rounded px-3 py-1.5 text-sm focus:border-accent outline-none"
        />
        <div className="flex flex-wrap gap-1 mt-2">
          {filters.map((f) => (
            <button
              key={f.value}
              onClick={() => setFilter(f.value)}
              className={clsx(
                "px-2 py-0.5 text-xs rounded transition",
                filter === f.value
                  ? "bg-accent text-bg"
                  : "bg-bg-hover text-text-muted hover:text-text",
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>
      <div className="overflow-y-auto flex-1">
        {filtered.length === 0 && (
          <div className="p-4 text-sm text-text-muted text-center">
            Немає об&apos;єктів за фільтром
          </div>
        )}
        {filtered.map((o) => {
          const status = (o.score?.status ?? "STABLE") as StatusT;
          const score = o.score?.score ?? 100;
          return (
            <button
              key={o.id}
              onClick={() => onSelect?.(o.id)}
              className={clsx(
                "w-full text-left p-3 border-b border-border flex items-center gap-3 transition",
                selectedId === o.id
                  ? "bg-bg-hover"
                  : "hover:bg-bg-hover/50",
              )}
            >
              <ScoreRing score={score} size={48} thickness={5} />
              <div className="flex-1 min-w-0">
                <div className="font-medium text-sm truncate">{o.name}</div>
                <div className="text-xs text-text-muted truncate">
                  {OBJECT_TYPE_UA[o.type]} · {o.district}
                </div>
                {o.telemetry && (
                  <div className="text-xs text-text-muted mt-0.5 font-mono">
                    {o.telemetry.battery_pct.toFixed(0)}% batt ·{" "}
                    {o.telemetry.occupancy}/{o.capacity}
                  </div>
                )}
              </div>
              <div
                className={clsx(
                  "w-1 self-stretch rounded-full",
                  status === "STABLE" && "bg-ok",
                  status === "WARNING" && "bg-warn",
                  status === "CRITICAL" && "bg-crit",
                  status === "RESCUE_IN_TRANSIT" && "bg-rescue",
                )}
              />
            </button>
          );
        })}
      </div>
    </div>
  );
}