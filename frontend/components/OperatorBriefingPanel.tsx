"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { Briefing } from "@/lib/types";

interface OperatorBriefingPanelProps {
  objectId: string;
  onClose: () => void;
}

const SEVERITY_STYLES: Record<
  Briefing["severity"],
  { border: string; bg: string; text: string; icon: string; label: string }
> = {
  STABLE: {
    border: "border-secondary/30",
    bg: "bg-secondary-container/10",
    text: "text-secondary",
    icon: "check_circle",
    label: "Стабільно",
  },
  WARNING: {
    border: "border-tertiary/30",
    bg: "bg-tertiary-container/10",
    text: "text-tertiary",
    icon: "warning",
    label: "Увага",
  },
  CRITICAL: {
    border: "border-error/30",
    bg: "bg-error-container/10",
    text: "text-error",
    icon: "error",
    label: "Критично",
  },
};

export function OperatorBriefingPanel({
  objectId,
  onClose,
}: OperatorBriefingPanelProps) {
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [usedLlm, setUsedLlm] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function load(useLlm: boolean) {
    setLoading(true);
    setError(null);
    setUsedLlm(useLlm);
    try {
      const data = await api.briefing(objectId, useLlm);
      setBriefing(data);
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
            <i className="material-symbols-outlined text-primary">auto_awesome</i>
            <h2 className="text-xl font-semibold text-on-surface">
              AI-брифінг для оператора
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

        {!briefing && !loading && (
          <div className="flex flex-col gap-4">
            <p className="text-sm text-on-surface-variant">
              Згенерувати людино-читабельний брифінг на основі ML-прогнозу,
              SHAP-пояснень, anomaly detection та forecast.
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => load(false)}
                className="flex-1 bg-primary text-on-primary font-semibold py-3 rounded-lg hover:bg-primary-container transition-colors flex items-center justify-center gap-2"
              >
                <i className="material-symbols-outlined text-[18px]">bolt</i>
                Template (миттєво)
              </button>
              <button
                onClick={() => load(true)}
                className="flex-1 bg-tertiary-container/20 text-tertiary border border-tertiary/30 font-semibold py-3 rounded-lg hover:bg-tertiary-container/30 transition-colors flex items-center justify-center gap-2"
                title="Потребує OPENAI_API_KEY на сервері"
              >
                <i className="material-symbols-outlined text-[18px]">auto_awesome</i>
                LLM (якщо налаштовано)
              </button>
            </div>
            {error && (
              <div className="text-sm text-error bg-error-container/10 border border-error/20 rounded p-2">
                {error}
              </div>
            )}
          </div>
        )}

        {loading && (
          <div className="flex flex-col items-center justify-center py-12 gap-3">
            <i className="material-symbols-outlined text-[48px] text-primary animate-spin">
              progress_activity
            </i>
            <p className="text-sm text-on-surface-variant">
              {usedLlm ? "LLM генерує брифінг..." : "Генерую брифінг..."}
            </p>
          </div>
        )}

        {briefing && !loading && <BriefingContent briefing={briefing} />}
      </div>
    </div>
  );
}

function BriefingContent({ briefing }: { briefing: Briefing }) {
  const sev = SEVERITY_STYLES[briefing.severity];
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`inline-flex items-center gap-1 px-2 py-1 rounded font-bold text-[11px] uppercase tracking-wider border ${sev.border} ${sev.bg} ${sev.text}`}
        >
          <i className="material-symbols-outlined text-[14px]">{sev.icon}</i>
          {sev.label}
        </span>
        <span className="inline-flex items-center gap-1 bg-surface-container-high text-on-surface px-2 py-1 rounded font-mono text-[11px] border border-outline-variant/20">
          <i className="material-symbols-outlined text-[12px]">psychology</i>
          {briefing.method === "llm" ? "GPT-4o-mini" : "Template engine"}
        </span>
        <span className="inline-flex items-center gap-1 bg-primary-container/20 text-primary px-2 py-1 rounded font-mono text-[11px] border border-primary/30">
          confidence: {(briefing.model_confidence * 100).toFixed(0)}%
        </span>
      </div>

      <div className={`p-3 rounded-lg border ${sev.border} ${sev.bg}`}>
        <p className="text-[14px] text-on-surface leading-relaxed">
          {briefing.summary}
        </p>
      </div>

      <div>
        <div className="flex items-center gap-2 mb-2">
          <i className="material-symbols-outlined text-[18px] text-primary">
            priority_high
          </i>
          <h3 className="font-bold text-[12px] uppercase tracking-wider text-on-surface-variant">
            Рекомендовані дії
          </h3>
        </div>
        <ul className="flex flex-col gap-2">
          {briefing.recommended_actions.map((action, idx) => (
            <li
              key={idx}
              className="flex items-start gap-2 text-[13px] text-on-surface bg-surface-bright/30 border border-outline-variant/10 rounded p-2"
            >
              <span className="text-primary font-mono text-[11px] mt-0.5 shrink-0">
                {String(idx + 1).padStart(2, "0")}
              </span>
              <span>{action}</span>
            </li>
          ))}
        </ul>
      </div>

      {briefing.key_factors.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-2">
            <i className="material-symbols-outlined text-[18px] text-primary">
              insights
            </i>
            <h3 className="font-bold text-[12px] uppercase tracking-wider text-on-surface-variant">
              Топ-фактори ML (SHAP)
            </h3>
          </div>
          <div className="flex flex-col gap-1">
            {briefing.key_factors.map((f) => (
              <div
                key={f.feature}
                className="flex justify-between font-mono text-[12px] py-1.5 border-b border-outline-variant/10"
              >
                <span className="text-on-surface-variant">{f.feature}</span>
                <span
                  className={
                    f.contribution > 0 ? "text-secondary" : "text-error"
                  }
                >
                  {f.contribution > 0 ? "+" : ""}
                  {f.contribution.toFixed(2)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
