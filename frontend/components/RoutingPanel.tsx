"use client";

import { useState } from "react";
import { clsx } from "clsx";
import type { RoutingRecommendation, ResourceTypeT } from "@/lib/types";
import { RESOURCE_TYPE_UA } from "@/lib/types";

interface RoutingPanelProps {
  recommendations: RoutingRecommendation[];
  onAssign?: (object_id: string, resource_type: ResourceTypeT) => Promise<void>;
}

export function RoutingPanel({ recommendations, onAssign }: RoutingPanelProps) {
  const [assigning, setAssigning] = useState<string | null>(null);

  const resources: ResourceTypeT[] = [
    "GENERATOR",
    "BATTERY_BANK",
    "STARLINK",
    "TECH_TEAM",
    "FUEL",
  ];

  async function handleAssign(objId: string, rt: ResourceTypeT) {
    setAssigning(`${objId}:${rt}`);
    try {
      await onAssign?.(objId, rt);
    } finally {
      setAssigning(null);
    }
  }

  return (
    <div className="panel p-3 h-full flex flex-col">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h2 className="text-sm font-semibold">Напрямок ресурсів</h2>
          <p className="text-xs text-on-surface-variant">
            Куди направити допомогу зараз — рекомендація AI
          </p>
        </div>
        <span className="px-2 py-0.5 rounded text-xs font-bold uppercase tracking-wider bg-primary/20 text-primary border border-primary/30">
          Топ-{recommendations.length}
        </span>
      </div>

      <div className="overflow-y-auto flex-1 space-y-2">
        {recommendations.length === 0 && (
          <div className="text-sm text-on-surface-variant text-center py-8">
            Усі об&apos;єкти стабільні — рекомендацій немає
          </div>
        )}
        {recommendations.map((r, idx) => {
          const pctColor =
            r.priority_score >= 70
              ? "bg-error"
              : r.priority_score >= 40
                ? "bg-tertiary"
                : "bg-on-surface-variant";
          return (
            <div key={r.object_id} className="card p-3 transition hover:bg-surface-bright/10 ai-action-border">
              <div className="flex items-start justify-between">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs text-primary">#{idx + 1}</span>
                    <span className="font-medium text-sm truncate">{r.object_name}</span>
                  </div>
                  <div className="text-xs text-on-surface-variant mt-0.5">
                    {r.district} · пріоритет {r.priority_score}
                  </div>
                </div>
                <div className="text-right">
                  <div className="font-mono text-sm">
                    {r.time_to_critical_min
                      ? `~${Math.round(r.time_to_critical_min)} хв`
                      : "стабільно"}
                  </div>
                  <div className="text-xs text-on-surface-variant">до критики</div>
                </div>
              </div>

              {/* Пріоритет-бар */}
              <div className="mt-2">
                <div className="h-1 bg-outline-variant/30 rounded-full overflow-hidden">
                  <div
                    className={clsx("h-full transition-all", pctColor)}
                    style={{ width: `${r.priority_score}%` }}
                  />
                </div>
              </div>

              {/* Обґрунтування */}
              <div className="text-xs text-on-surface-variant mt-2">{r.justification}</div>

              {/* Кнопки ресурсів */}
              <div className="mt-3 flex flex-wrap gap-1">
                {resources.map((rt) => {
                  const isAssigning =
                    assigning === `${r.object_id}:${rt}`;
                  return (
                    <button
                      key={rt}
                      disabled={isAssigning}
                      onClick={() => handleAssign(r.object_id, rt)}
                      className={clsx(
                        "text-xs px-2 py-1 rounded transition border",
                        isAssigning
                          ? "bg-primary text-on-primary border-primary"
                          : "bg-[#111827] border-outline-variant/30 text-on-surface-variant hover:text-on-surface hover:border-primary",
                      )}
                      title={`Направити ${RESOURCE_TYPE_UA[rt]}`}
                    >
                      {isAssigning ? "→" : RESOURCE_TYPE_UA[rt]}
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}