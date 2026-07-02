// Operator-friendly recommendations based on telemetry.
// Повертає просту людино-читабельну пораду для диспетчера + який саме
// ресурс доцільно направити. Кожен тип ресурсу відповідає своїй ситуації:
//   GENERATOR    — великий об'єкт без живлення й без генератора
//   BATTERY_BANK — малий пункт без живлення (швидке тимчасове живлення)
//   FUEL         — є генератор, але він заглух (скінчилось пальне)
//   STARLINK     — є живлення, але немає зв'язку (координація неможлива)
//   TECH_TEAM    — високий CO₂ / потрібна вентиляція чи ремонт
//   EVACUATION   — переповнення

import type { ObjectState, Score, StatusT, Telemetry } from "./types";

type Urgency = "ok" | "watch" | "act" | "critical";

export interface OperatorBrief {
  headline: string;
  recommendation: string;
  forecast: string;
  urgency: Urgency;
  /** Ресурс, який варто направити. undefined = нічого не потрібно. */
  suggestedResource?:
    | "GENERATOR"
    | "BATTERY_BANK"
    | "STARLINK"
    | "TECH_TEAM"
    | "FUEL"
    | "EVACUATION";
}

const URGENCY_RANK: Record<Urgency, number> = { ok: 0, watch: 1, act: 2, critical: 3 };

function atLeast(a: Urgency, b: Urgency): Urgency {
  return URGENCY_RANK[a] >= URGENCY_RANK[b] ? a : b;
}

function baseUrgency(
  status: StatusT,
  ttc: number | null,
  battery: number,
  powered: boolean
): Urgency {
  if (status === "CRITICAL") return "critical";
  if (status === "WARNING") return "act";
  if (status === "RESCUE_IN_TRANSIT") return "watch";
  if (!powered && battery < 30) return "act";
  if (ttc != null && ttc < 60) return "act";
  if (ttc != null && ttc < 180) return "watch";
  return "ok";
}

function formatHours(min: number): string {
  if (min >= 60) {
    const h = Math.floor(min / 60);
    const m = Math.round(min - h * 60);
    return m > 0 ? `~${h} год ${m} хв` : `~${h} год`;
  }
  return `~${Math.round(min)} хв`;
}

// Малий пункт (незламності) швидше запитати резервну батарею, ніж генератор.
const SMALL_CAPACITY = 120;

export function buildOperatorBrief(
  state: ObjectState,
  score: Score | null | undefined,
  telemetry: Telemetry | null | undefined
): OperatorBrief {
  const status = (score?.status ?? "STABLE") as StatusT;
  const ttc = score?.time_to_critical_min ?? null;
  const battery = telemetry?.battery_pct ?? 100;
  const estHours = telemetry?.battery_est_hours ?? null;
  const powerOn = telemetry?.power_on ?? true;
  const generatorOn = telemetry?.generator_on ?? false;
  const powered = powerOn || generatorOn;
  const connected = telemetry?.internet_on ?? true;
  const co2 = telemetry?.co2_ppm ?? 0;
  const occupancy = telemetry?.occupancy ?? 0;
  const capacity = state.capacity ?? 1;
  const occupancyPct = capacity > 0 ? (occupancy / capacity) * 100 : 0;
  const hasGenerator = state.has_generator ?? false;
  const hasStarlink = state.has_starlink ?? false;

  let urgency = baseUrgency(status, ttc, battery, powered);
  let recommendation = "Об'єкт стабільний. Продовжуйте моніторинг.";
  let suggestedResource: OperatorBrief["suggestedResource"] | undefined;

  if (status === "RESCUE_IN_TRANSIT") {
    recommendation = "Бригада вже виїхала. Дочекайтесь прибуття.";
  } else if (!powered && !hasGenerator) {
    // Немає жодного джерела живлення
    if (capacity <= SMALL_CAPACITY) {
      recommendation =
        "Малий пункт без живлення. Швидко підключити резервну батарею.";
      suggestedResource = "BATTERY_BANK";
    } else {
      recommendation = "Немає живлення. Доставити генератор.";
      suggestedResource = "GENERATOR";
    }
    urgency = atLeast(urgency, "act");
  } else if (!powered && hasGenerator) {
    // Генератор є, але не працює → найімовірніше скінчилось пальне
    recommendation =
      "Генератор заглух (пальне). Доставити паливо для перезапуску.";
    suggestedResource = "FUEL";
    urgency = atLeast(urgency, "act");
  } else if (!connected && !hasStarlink) {
    // Живлення є, але зв'язку немає — об'єкт «сліпий» для координації
    recommendation = "Живлення є, але зв'язок відсутній. Направити Starlink.";
    suggestedResource = "STARLINK";
    urgency = atLeast(urgency, "act");
  } else if (!connected && hasStarlink) {
    recommendation = "Є термінал Starlink, але зв'язок не активний. Активувати.";
    suggestedResource = "STARLINK";
    urgency = atLeast(urgency, "act");
  } else if (co2 > 1500 && occupancy > 0) {
    recommendation = "Високий рівень CO₂. Техбригада для вентиляції.";
    suggestedResource = "TECH_TEAM";
    urgency = atLeast(urgency, "act");
  } else if (occupancyPct > 90) {
    recommendation = "Переповнення. Розглянути часткову евакуацію людей.";
    suggestedResource = "EVACUATION";
    urgency = atLeast(urgency, "watch");
  } else if (urgency === "act" || urgency === "critical") {
    recommendation = "Стан погіршується. Підготувати генератор для доставки.";
    suggestedResource = capacity <= SMALL_CAPACITY ? "BATTERY_BANK" : "GENERATOR";
  } else if (urgency === "watch") {
    recommendation = "Стан під наглядом. Слідкувати за зарядом і зв'язком.";
  }

  // Headline
  let headline = "Все добре";
  if (status === "RESCUE_IN_TRANSIT") headline = "Допомога вже в дорозі";
  else if (urgency === "critical") headline = "Критично";
  else if (urgency === "act") headline = "Потрібна допомога";
  else if (urgency === "watch") headline = "Під наглядом";

  // Forecast
  let forecast = "Стабільно. Працює у звичайному режимі.";
  if (status === "RESCUE_IN_TRANSIT") {
    forecast = "Допомога прибуде найближчим часом.";
  } else if (!connected) {
    forecast = "Зв'язок відсутній — статус оновлюється з затримкою.";
  } else if (!powerOn && generatorOn && estHours != null) {
    forecast = `На генераторі. Запас пального — ${formatHours(estHours * 60)}.`;
  } else if (!powered && estHours != null && battery > 0) {
    forecast = `Автономності залишилось ${formatHours(estHours * 60)}.`;
  } else if (ttc != null && ttc > 0 && ttc < 60) {
    forecast = `Критичний стан через ${formatHours(ttc)}.`;
  } else if (ttc != null && ttc > 60) {
    forecast = `Запас міцності — ${formatHours(ttc)}.`;
  }

  return { headline, recommendation, forecast, urgency, suggestedResource };
}
