"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Counterfactual, InterventionTypeT } from "@/lib/types";

interface CounterfactualPanelProps {
  objectId: string;
  objectName: string;
  onClose: () => void;
}

const INTERVENTIONS: {
  value: InterventionTypeT;
  label: string;
  icon: string;
  description: string;
}[] = [
  {
    value: "generator",
    label: "Генератор",
    icon: "bolt",
    description: "живлення + заряд батареї",
  },
  {
    value: "tech_team",
    label: "Техбригада",
    icon: "engineering",
    description: "полагодити сенсори, CO₂/температура",
  },
  {
    value: "starlink",
    label: "Starlink",
    icon: "satellite_alt",
    description: "супутниковий інтернет",
  },
  {
    value: "fuel",
    label: "Паливо",
    icon: "local_gas_station",
    description: "+50% заряду, +8 год автономності",
  },
  {
    value: "evacuation",
    label: "Евакуація",
    icon: "directions_run",
    description: "вивести частину людей",
  },
];

export function CounterfactualPanel({
  objectId,
  objectName,
  onClose,
}: CounterfactualPanelProps) {
  const [intervention, setIntervention] = useState<InterventionTypeT>("generator");
  const [eta, setEta] = useState<number>(30);
  const [result, setResult] = useState<Counterfactual | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function run() {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await api.counterfactual(objectId, intervention, eta);
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-[100] bg-black/60 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="glass-card rounded-xl p-6 max-w-2xl w-full shadow-2xl border border-outline-variant/30 max-h-[85vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-start mb-4 gap-3">
          <div className="flex items-center gap-2">
            <i className="material-symbols-outlined text-primary">science</i>
            <h2 className="text-xl font-semibold text-on-surface">
              What-if: {objectName}
            </h2>
          </div>
          <button
            onClick={onClose}
            className="text-on-surface-variant hover:text-on-surface p-1 shrink-0"
            aria-label="Закрити"
          >
            <i className="material-symbols-outlined">close</i>
          </button>
        </div>

        <p className="text-sm text-on-surface-variant mb-4">
          Counterfactual аналіз: <b>ML inference</b> обчислює, як зміниться
          Resilience Score об'єкта, якщо застосувати втручання.
        </p>

        <div className="flex flex-col gap-4">
          <div>
            <label className="text-[12px] font-bold uppercase tracking-wider text-on-surface-variant mb-2 block">
              Тип втручання
            </label>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {INTERVENTIONS.map((iv) => (
                <button
                  key={iv.value}
                  onClick={() => setIntervention(iv.value)}
                  className={`p-2 rounded border text-left transition-colors ${
                    intervention === iv.value
                      ? "bg-primary/20 border-primary text-primary"
                      : "bg-surface-bright/20 border-outline-variant/30 text-on-surface-variant hover:border-primary/50"
                  }`}
                >
                  <div className="flex items-center gap-1.5 mb-0.5">
                    <i className="material-symbols-outlined text-[16px]">
                      {iv.icon}
                    </i>
                    <span className="text-[12px] font-bold">{iv.label}</span>
                  </div>
                  <div className="text-[10px] opacity-70 leading-tight">
                    {iv.description}
                  </div>
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="text-[12px] font-bold uppercase tracking-wider text-on-surface-variant mb-2 block">
              ETA: <span className="text-primary">{eta} хв</span>
            </label>
            <input
              type="range"
              min={5}
              max={120}
              step={5}
              value={eta}
              onChange={(e) => setEta(Number(e.target.value))}
              className="w-full accent-primary"
            />
          </div>

          <button
            onClick={run}
            disabled={loading}
            className="bg-primary text-on-primary font-semibold py-3 rounded-lg hover:bg-primary-container transition-colors flex items-center justify-center gap-2 disabled:opacity-50"
          >
            {loading ? (
              <>
                <i className="material-symbols-outlined text-[18px] animate-spin">
                  progress_activity
                </i>
                Обчислюю ML...
              </>
            ) : (
              <>
                <i className="material-symbols-outlined text-[18px]">
                  play_arrow
                </i>
                Запустити what-if
              </>
            )}
          </button>

          {error && (
            <div className="text-sm text-error bg-error-container/10 border border-error/20 rounded p-2">
              {error}
            </div>
          )}

          {result && <CounterfactualResult result={result} />}
        </div>
      </div>
    </div>
  );
}

function CounterfactualResult({ result }: { result: Counterfactual }) {
  const delta = result.score_delta;
  const isPositive = delta > 0;
  const isSignificant = Math.abs(delta) >= 0.5;
  return (
    <div className="flex flex-col gap-3 pt-4 border-t border-outline-variant/20">
      <div className="grid grid-cols-2 gap-3">
        <div className="bg-surface-bright/20 border border-outline-variant/20 rounded-lg p-3">
          <div className="text-[10px] font-bold uppercase tracking-wider text-on-surface-variant mb-1">
            БЕЗ втручання
          </div>
          <div className="text-[28px] font-bold text-on-surface leading-none">
            {result.before.score.toFixed(1)}
          </div>
          <div className="text-[12px] text-on-surface-variant mt-1">
            {result.before.status}
          </div>
          {result.before.ttc_min != null && (
            <div className="text-[11px] font-mono text-tertiary mt-0.5">
              ⏱ {result.before.ttc_min.toFixed(0)} хв
            </div>
          )}
        </div>
        <div
          className={`border rounded-lg p-3 ${
            isSignificant
              ? isPositive
                ? "bg-secondary-container/10 border-secondary/30"
                : "bg-error-container/10 border-error/30"
              : "bg-surface-bright/20 border-outline-variant/20"
          }`}
        >
          <div className="text-[10px] font-bold uppercase tracking-wider text-on-surface-variant mb-1">
            ПІСЛЯ {result.intervention_label.toUpperCase()}
          </div>
          <div
            className={`text-[28px] font-bold leading-none ${
              isPositive ? "text-secondary" : isSignificant ? "text-error" : "text-on-surface"
            }`}
          >
            {result.after.score.toFixed(1)}
          </div>
          <div className="text-[12px] text-on-surface-variant mt-1">
            {result.after.status}
          </div>
          {result.after.ttc_min != null && (
            <div className="text-[11px] font-mono text-tertiary mt-0.5">
              ⏱ {result.after.ttc_min.toFixed(0)} хв
            </div>
          )}
        </div>
      </div>

      <div
        className={`flex items-center justify-center gap-2 py-2 rounded ${
          isPositive ? "bg-secondary/10" : "bg-error/10"
        }`}
      >
        <i
          className={`material-symbols-outlined ${
            isPositive ? "text-secondary" : "text-error"
          }`}
        >
          {isPositive ? "trending_up" : "trending_down"}
        </i>
        <span
          className={`font-mono text-[20px] font-bold ${
            isPositive ? "text-secondary" : "text-error"
          }`}
        >
          {delta > 0 ? "+" : ""}
          {delta.toFixed(1)}
        </span>
        <span className="text-[12px] text-on-surface-variant">балів</span>
        {result.will_rescue && (
          <span className="ml-2 inline-flex items-center gap-1 text-secondary text-[11px] font-bold">
            <i className="material-symbols-outlined text-[14px]">check_circle</i>
            Покращить статус
          </span>
        )}
      </div>

      {result.top_feature_changes.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-2">
            <i className="material-symbols-outlined text-[16px] text-primary">
              insights
            </i>
            <h4 className="text-[11px] font-bold uppercase tracking-wider text-on-surface-variant">
              Які фічі ML найбільше змінилися
            </h4>
          </div>
          <div className="flex flex-col gap-1">
            {result.top_feature_changes.map((fc) => (
              <div
                key={fc.feature}
                className="flex items-center justify-between text-[12px] py-1 border-b border-outline-variant/10"
              >
                <span className="text-on-surface-variant font-mono">
                  {fc.feature}
                </span>
                <div className="flex items-center gap-2 font-mono">
                  <span className="text-on-surface-variant">
                    {fc.before >= 0 ? "+" : ""}
                    {fc.before.toFixed(2)}
                  </span>
                  <i className="material-symbols-outlined text-[12px] text-on-surface-variant">
                    arrow_forward
                  </i>
                  <span
                    className={
                      fc.after > fc.before
                        ? "text-secondary font-bold"
                        : "text-error font-bold"
                    }
                  >
                    {fc.after >= 0 ? "+" : ""}
                    {fc.after.toFixed(2)}
                  </span>
                  <span
                    className={`text-[10px] ${
                      fc.delta > 0 ? "text-secondary" : "text-error"
                    }`}
                  >
                    ({fc.delta > 0 ? "+" : ""}
                    {fc.delta.toFixed(2)})
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="bg-primary/10 border border-primary/30 rounded p-2 text-[12px] text-on-surface">
        {result.recommendation}
      </div>
    </div>
  );
}
