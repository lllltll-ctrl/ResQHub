"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { ModelCard, ModelHealth } from "@/lib/types";

export default function ModelsPage() {
  const [cards, setCards] = useState<ModelCard[]>([]);
  const [health, setHealth] = useState<ModelHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [c, h] = await Promise.all([api.modelCards(), api.modelHealth()]);
        if (!cancelled) {
          setCards(c);
          setHealth(h);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="min-h-screen flex flex-col">
      <nav className="fixed top-0 left-0 right-0 z-50 bg-surface-container-lowest/80 backdrop-blur-xl border-b border-outline-variant/20 h-16 flex items-center px-6">
        <div className="flex items-center gap-3">
          <Link
            href="/"
            className="text-[20px] font-bold text-on-surface tracking-tight"
          >
            ResQHub
          </Link>
          <span className="text-on-surface-variant/30 mx-1">|</span>
          <Link
            href="/operations"
            className="text-[14px] text-on-surface-variant hover:text-on-surface"
          >
            Операційна
          </Link>
          <Link
            href="/analytics"
            className="text-[14px] text-on-surface-variant hover:text-on-surface"
          >
            Аналітика
          </Link>
          <Link
            href="/resident"
            className="text-[14px] text-on-surface-variant hover:text-on-surface"
          >
            Жителю
          </Link>
          <span className="text-[14px] text-primary font-bold">
            ML Governance
          </span>
        </div>
      </nav>

      <main className="flex-1 pt-24 pb-8 px-4 md:px-[32px] max-w-6xl mx-auto w-full">
        <h1 className="text-[32px] md:text-[40px] font-bold text-on-surface tracking-tight font-[DM_Sans]">
          ML Governance
        </h1>
        <p className="text-on-surface-variant mt-2 max-w-2xl">
          Model cards, метрики і health для всіх моделей ResQHub. Це
          best-practice з Google Model Cards framework — кожна модель має
          документацію про intended use, метрики, обмеження і етичні
          аспекти.
        </p>

        {loading && (
          <div className="flex items-center justify-center py-12 gap-3 mt-8">
            <i className="material-symbols-outlined text-[36px] text-primary animate-spin">
              progress_activity
            </i>
            <p className="text-on-surface-variant">Завантажую model cards...</p>
          </div>
        )}

        {error && (
          <div className="mt-8 text-error bg-error-container/10 border border-error/20 rounded p-3">
            {error}
          </div>
        )}

        {health && !loading && <HealthBanner health={health} />}

        {cards.length > 0 && !loading && (
          <div className="mt-6 grid grid-cols-1 lg:grid-cols-2 gap-4">
            {cards.map((card) => (
              <ModelCardView key={card.model_name} card={card} />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}

function HealthBanner({ health }: { health: ModelHealth }) {
  const ol = health.online_learner;
  return (
    <div className="mt-6 grid grid-cols-1 sm:grid-cols-3 gap-3">
      <div className="bg-surface-container-low border border-outline-variant/30 rounded-lg p-4">
        <div className="flex items-center gap-2 text-on-surface-variant text-[11px] uppercase tracking-wider font-bold">
          <i className="material-symbols-outlined text-[16px]">model_training</i>
          Model versions
        </div>
        <div className="mt-2 space-y-1 text-sm font-mono">
          {Object.entries(health.models).map(([k, v]) => (
            <div key={k} className="flex justify-between">
              <span className="text-on-surface-variant">{k}:</span>
              <span className="text-primary font-bold">{v}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="bg-surface-container-low border border-outline-variant/30 rounded-lg p-4">
        <div className="flex items-center gap-2 text-on-surface-variant text-[11px] uppercase tracking-wider font-bold">
          <i className="material-symbols-outlined text-[16px]">online_prediction</i>
          Online Learner
        </div>
        <div className="mt-2 space-y-1 text-sm font-mono">
          <div className="flex justify-between">
            <span className="text-on-surface-variant">Status:</span>
            <span
              className={ol.is_warm ? "text-secondary" : "text-tertiary"}
            >
              {ol.is_warm ? "warm" : "cold start"}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-on-surface-variant">Observations:</span>
            <span className="text-on-surface">{ol.n_observations}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-on-surface-variant">Drifts detected:</span>
            <span
              className={
                ol.n_drifts_detected > 0 ? "text-error" : "text-on-surface"
              }
            >
              {ol.n_drifts_detected}
            </span>
          </div>
        </div>
      </div>

      <div className="bg-surface-container-low border border-outline-variant/30 rounded-lg p-4">
        <div className="flex items-center gap-2 text-on-surface-variant text-[11px] uppercase tracking-wider font-bold">
          <i className="material-symbols-outlined text-[16px]">verified</i>
          Training
        </div>
        <div className="mt-2 space-y-1 text-sm font-mono">
          {Object.entries(health.artifacts).map(([k, v]) =>
            v.trained_at ? (
              <div key={k} className="flex justify-between">
                <span className="text-on-surface-variant">{k}:</span>
                <span className="text-on-surface text-[11px]">
                  {new Date(v.trained_at).toLocaleDateString("uk-UA")}
                </span>
              </div>
            ) : null,
          )}
        </div>
      </div>
    </div>
  );
}

function ModelCardView({ card }: { card: ModelCard }) {
  const typeIcons: Record<string, string> = {
    regression: "show_chart",
    classification: "category",
    ranker: "format_list_numbered",
    anomaly_detection: "radar",
    drift_detection: "monitoring",
  };
  const icon = typeIcons[card.model_type] ?? "model_training";

  return (
    <div className="bg-surface-container-low border border-outline-variant/30 rounded-lg p-5 flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <i className={`material-symbols-outlined text-[24px] text-primary`}>
            {icon}
          </i>
          <div>
            <h3 className="font-bold text-on-surface text-[16px]">
              {card.model_name}
            </h3>
            <span className="text-[11px] text-on-surface-variant font-mono">
              v{card.model_version} · {card.model_type}
            </span>
          </div>
        </div>
        <span className="bg-primary-container/20 text-primary px-2 py-0.5 rounded text-[10px] font-mono border border-primary/30">
          MODEL CARD
        </span>
      </div>

      <p className="text-[13px] text-on-surface">{card.intended_use}</p>

      <div>
        <div className="text-[10px] font-bold uppercase tracking-wider text-on-surface-variant mb-1">
          Metrics
        </div>
        <div className="grid grid-cols-2 gap-1 text-[12px] font-mono">
          {Object.entries(card.metrics).map(([k, v]) => (
            <div key={k} className="flex justify-between bg-surface-bright/30 px-2 py-1 rounded">
              <span className="text-on-surface-variant">{k}</span>
              <span className="text-primary font-bold">
                {typeof v === "number" ? v.toFixed(3) : v}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div>
        <div className="text-[10px] font-bold uppercase tracking-wider text-on-surface-variant mb-1">
          Features ({card.features.length})
        </div>
        <div className="flex flex-wrap gap-1">
          {card.features.slice(0, 8).map((f) => (
            <span
              key={f}
              className="text-[10px] font-mono bg-surface-bright/40 border border-outline-variant/20 px-1.5 py-0.5 rounded"
            >
              {f}
            </span>
          ))}
          {card.features.length > 8 && (
            <span className="text-[10px] text-on-surface-variant">
              +{card.features.length - 8} more
            </span>
          )}
        </div>
      </div>

      {card.limitations.length > 0 && (
        <div>
          <div className="text-[10px] font-bold uppercase tracking-wider text-tertiary mb-1">
            Limitations
          </div>
          <ul className="text-[12px] text-on-surface-variant space-y-0.5">
            {card.limitations.slice(0, 3).map((l, i) => (
              <li key={i} className="flex items-start gap-1">
                <span className="text-tertiary mt-0.5">•</span>
                <span>{l}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="pt-2 border-t border-outline-variant/10 text-[10px] text-on-surface-variant flex justify-between">
        <span>{card.training_data}</span>
        <span className="font-mono">{card.owner}</span>
      </div>
    </div>
  );
}
