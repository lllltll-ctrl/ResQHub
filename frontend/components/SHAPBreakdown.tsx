"use client";

import { useMemo } from "react";

interface ShapBreakdownProps {
  components: Record<string, unknown>;
}

const SCORE_KEYS = new Set([
  "ml_feature_battery",
  "ml_feature_temp",
  "ml_feature_co2",
  "ml_feature_occupancy_ratio",
  "ml_feature_criticality",
]);

const CONFIDENCE_KEYS = new Set([
  "ml_prediction_confidence",
  "ml_tree_spread",
  "forecast_confidence",
  "forecast_slope_pct_per_min",
]);

const INPUT_KEYS = new Set([
  "input_battery_pct",
  "input_co2_ppm",
  "input_occupancy_ratio",
]);

const BOOLEAN_KEYS = new Set([
  "generator_bonus",
  "starlink_bonus",
]);

const ANOMALY_BOOL_KEYS = new Set([
  "anomaly_is_anomaly",
]);

const ANOMALY_TEXT_KEYS = new Set([
  "anomaly_reason",
]);

const ANOMALY_NUM_KEYS = new Set([
  "anomaly_score",
]);

const HIDDEN_KEYS = new Set([
  "ml_features_used",
  "ml_features",
]);

const LABEL_UA: Record<string, string> = {
  ml_feature_battery: "Батарея",
  ml_feature_temp: "Температура",
  ml_feature_co2: "CO₂",
  ml_feature_occupancy_ratio: "Заповненість",
  ml_feature_criticality: "Критичність",
  ml_prediction_confidence: "Впевненість ML",
  ml_tree_spread: "Розкид дерев RF",
  forecast_confidence: "Впевненість прогнозу",
  forecast_slope_pct_per_min: "Нахил прогнозу (%/хв)",
  input_battery_pct: "Вхід: батарея",
  input_co2_ppm: "Вхід: CO₂",
  input_occupancy_ratio: "Вхід: заповненість",
  generator_bonus: "Бонус генератора",
  starlink_bonus: "Бонус Starlink",
};

function humanize(key: string): string {
  return LABEL_UA[key] ?? key.replace(/_/g, " ");
}

function isShapObject(value: unknown): value is Record<string, number> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const entries = Object.entries(value as Record<string, unknown>);
  if (entries.length === 0) return false;
  return entries.every(([, v]) => typeof v === "number");
}

export function ShapBreakdown({ components }: ShapBreakdownProps) {
  const { modelVersion, shapContribs, inputRows, confidenceRows, scoreRows, otherRows, anomaly } =
    useMemo(() => parseComponents(components), [components]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        {modelVersion && (
          <span className="inline-flex items-center gap-1 bg-primary-container/20 text-primary px-2 py-0.5 rounded font-mono text-[11px] border border-primary/30">
            <i className="material-symbols-outlined text-[12px]">model_training</i>
            model {modelVersion}
          </span>
        )}
        {confidenceRows.map((row) => (
          <span
            key={row.key}
            className="inline-flex items-center gap-1 bg-surface-container-high text-on-surface px-2 py-0.5 rounded font-mono text-[11px] border border-outline-variant/20"
          >
            <i className="material-symbols-outlined text-[12px]">psychology</i>
            {humanize(row.key)}: <b className="text-primary">{row.display}</b>
          </span>
        ))}
      </div>

      {anomaly.isAnomaly && (
        <div className="rounded-lg border border-error/30 bg-error-container/10 p-3 flex flex-col gap-1">
          <div className="flex items-center gap-2 text-error">
            <i className="material-symbols-outlined text-[18px]">warning</i>
            <span className="font-bold text-[12px] uppercase tracking-wider">
              Аномалія сенсорів
            </span>
            {anomaly.score != null && (
              <span className="ml-auto font-mono text-[11px] text-on-surface-variant">
                score: {anomaly.score.toFixed(3)}
              </span>
            )}
          </div>
          {anomaly.reason && (
            <p className="text-[12px] text-on-surface-variant">{anomaly.reason}</p>
          )}
        </div>
      )}

      {shapContribs.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-2">
            <i className="material-symbols-outlined text-[16px] text-primary">insights</i>
            <h5 className="text-[11px] font-bold uppercase tracking-wider text-on-surface-variant">
              SHAP-пояснення (що вплинуло на score)
            </h5>
          </div>
          <div className="flex flex-col gap-1.5">
            {shapContribs.map((row) => (
              <ShapBar key={row.key} label={humanize(row.key)} value={row.value} />
            ))}
          </div>
        </div>
      )}

      {scoreRows.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-2">
            <i className="material-symbols-outlined text-[16px] text-secondary">monitoring</i>
            <h5 className="text-[11px] font-bold uppercase tracking-wider text-on-surface-variant">
              Сирі значення фіч
            </h5>
          </div>
          <div className="flex flex-col gap-1">
            {scoreRows.map((row) => (
              <div
                key={row.key}
                className="flex justify-between font-mono text-[12px] py-1 border-b border-outline-variant/10"
              >
                <span className="text-on-surface-variant">{humanize(row.key)}</span>
                <span className="text-on-surface font-bold">{row.display}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {inputRows.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-2">
            <i className="material-symbols-outlined text-[16px] text-on-surface-variant">input</i>
            <h5 className="text-[11px] font-bold uppercase tracking-wider text-on-surface-variant">
              Вхідні дані
            </h5>
          </div>
          <div className="flex flex-col gap-1">
            {inputRows.map((row) => (
              <div
                key={row.key}
                className="flex justify-between font-mono text-[12px] py-1 border-b border-outline-variant/10"
              >
                <span className="text-on-surface-variant">{humanize(row.key)}</span>
                <span className="text-on-surface font-bold">{row.display}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {otherRows.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-2">
            <i className="material-symbols-outlined text-[16px] text-on-surface-variant">more_horiz</i>
            <h5 className="text-[11px] font-bold uppercase tracking-wider text-on-surface-variant">
              Інше
            </h5>
          </div>
          <div className="flex flex-col gap-1">
            {otherRows.map((row) => (
              <div
                key={row.key}
                className="flex justify-between font-mono text-[12px] py-1 border-b border-outline-variant/10"
              >
                <span className="text-on-surface-variant">{humanize(row.key)}</span>
                <span className="text-on-surface font-bold">{row.display}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

interface Row {
  key: string;
  value: number;
  display: string;
}

function parseComponents(components: Record<string, unknown>) {
  let modelVersion: string | null = null;
  let shapContribs: Row[] = [];
  const scoreRows: Row[] = [];
  const inputRows: Row[] = [];
  const confidenceRows: Row[] = [];
  const otherRows: Row[] = [];
  const anomaly: { isAnomaly: boolean; reason: string | null; score: number | null } = {
    isAnomaly: false,
    reason: null,
    score: null,
  };

  for (const [key, raw] of Object.entries(components)) {
    if (key === "model_version" && typeof raw === "string") {
      modelVersion = raw;
      continue;
    }
    if (HIDDEN_KEYS.has(key)) continue;

    if (ANOMALY_BOOL_KEYS.has(key) && typeof raw === "boolean") {
      anomaly.isAnomaly = raw;
      continue;
    }
    if (ANOMALY_TEXT_KEYS.has(key) && typeof raw === "string") {
      anomaly.reason = raw;
      continue;
    }
    if (ANOMALY_NUM_KEYS.has(key) && typeof raw === "number") {
      anomaly.score = raw;
      continue;
    }

    if (isShapObject(raw)) {
      shapContribs = Object.entries(raw)
        .map(([k, v]) => ({
          key: k,
          value: v,
          display: v.toFixed(2),
        }))
        .sort((a, b) => Math.abs(b.value) - Math.abs(a.value));
      continue;
    }

    if (Array.isArray(raw)) continue;

    if (typeof raw === "string") {
      otherRows.push({ key, value: NaN, display: raw });
      continue;
    }

    if (typeof raw === "boolean") {
      otherRows.push({ key, value: raw ? 1 : 0, display: raw ? "Так" : "Ні" });
      continue;
    }

    if (typeof raw === "number") {
      const row: Row = { key, value: raw, display: formatNumber(raw) };
      if (SCORE_KEYS.has(key)) scoreRows.push(row);
      else if (CONFIDENCE_KEYS.has(key)) confidenceRows.push(row);
      else if (INPUT_KEYS.has(key)) inputRows.push(row);
      else if (BOOLEAN_KEYS.has(key))
        otherRows.push({ ...row, display: raw ? "Так" : "Ні" });
      else otherRows.push(row);
    }
  }

  return { modelVersion, shapContribs, scoreRows, inputRows, confidenceRows, otherRows, anomaly };
}

function formatNumber(n: number): string {
  if (Number.isInteger(n)) return String(n);
  if (Math.abs(n) < 1) return n.toFixed(3);
  if (Math.abs(n) < 10) return n.toFixed(2);
  return n.toFixed(1);
}

function ShapBar({ label, value }: { label: string; value: number }) {
  const isPositive = value > 0;
  const absMagnitude = Math.min(20, Math.abs(value));
  const widthPct = (absMagnitude / 20) * 50;
  const color = isPositive ? "#4ae176" : "#ffb4ab";
  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex justify-between font-mono text-[11px]">
        <span className="text-on-surface-variant">{label}</span>
        <span style={{ color }}>
          {isPositive ? "+" : ""}
          {value.toFixed(2)}
        </span>
      </div>
      <div className="relative w-full h-1.5 bg-surface-container-high rounded-full overflow-hidden">
        <div className="absolute inset-y-0 left-1/2 w-px bg-outline-variant/40" />
        <div
          className="absolute inset-y-0 rounded-full"
          style={
            isPositive
              ? { left: "50%", width: `${widthPct}%`, background: color }
              : { right: "50%", width: `${widthPct}%`, background: color }
          }
        />
      </div>
    </div>
  );
}
