"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { RealtimeProvider } from "@/components/RealtimeProvider";
import { useStore } from "@/lib/store";
import { api } from "@/lib/api";
import { CityMap } from "@/components/CityMap";
import { RoutingPanel } from "@/components/RoutingPanel";
import { EventLog } from "@/components/EventLog";
import { ScoreRing } from "@/components/ScoreRing";
import { StatCard } from "@/components/StatCard";
import { ToastContainer, pushToast } from "@/components/Toast";
import { HeaderActions } from "@/components/HeaderActions";
import { StatusPill } from "@/components/ui/StatusPill";
import { ShapBreakdown } from "@/components/SHAPBreakdown";
import { OperatorBriefingPanel } from "@/components/OperatorBriefingPanel";
import { RESOURCE_TYPE_UA, SCENARIO_TYPE_UA } from "@/lib/types";
import Link from "next/link";
import type { ObjectState, ResourceTypeT } from "@/lib/types";

export default function OperationsPage() {
  return (
    <RealtimeProvider>
      <OperationsShell />
      <ToastContainer />
    </RealtimeProvider>
  );
}

function OperationsShell() {
  const {
    summary,
    objects,
    routing,
    activeScenario,
    selectedObjectId,
    setSelectedObjectId,
    wsConnected,
  } = useStore();

  const [clock, setClock] = useState<string>("");
  useEffect(() => {
    const t = setInterval(() => {
      setClock(new Date().toLocaleTimeString("uk-UA"));
    }, 1000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    if (!selectedObjectId) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setSelectedObjectId(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectedObjectId, setSelectedObjectId]);

  const selectedObject = objects.find((o) => o.id === selectedObjectId) ?? null;
  const [briefingObjectId, setBriefingObjectId] = useState<string | null>(null);

  async function handleScenario(type: "BLACKOUT" | "RESET" | "SIGNAL_DOWN" | "PARTIAL_OUTAGE") {
    try {
      await api.startScenario(type, "CITY", null, 1.0);
      const names: Record<string, string> = {
        BLACKOUT: "Блекаут",
        RESET: "Скидання",
        SIGNAL_DOWN: "Зв'язок відсутній",
        PARTIAL_OUTAGE: "Часткове відключення",
      };
      pushToast(`Сценарій «${names[type]}» запущено`, type === "RESET" ? "success" : "warning");
    } catch (e) {
      console.error(e);
      pushToast("Помилка запуску сценарію", "error");
    }
  }

  async function handleAssign(object_id: string, resource_type: ResourceTypeT) {
    try {
      await api.createAssignment(object_id, resource_type);
      pushToast(`Направлено: ${RESOURCE_TYPE_UA[resource_type]} на об'єкт`, "success");
    } catch (e) {
      console.error(e);
      pushToast(`Помилка призначення`, "error");
    }
  }

  const stable = summary?.stable ?? 0;
  const warning = summary?.warning ?? 0;
  const critical = summary?.critical ?? 0;
  const rescue = summary?.rescue_in_transit ?? 0;
  const total = summary?.total_objects ?? 10;

  // Реальний тренд: зберігаємо попереднє значення avg_city_score для порівняння
  const prevScoreRef = useRef<number | null>(null);
  const currentScore = summary?.avg_city_score ?? 0;
  const scoreDelta =
    prevScoreRef.current != null
      ? Math.round((currentScore - prevScoreRef.current) * 10) / 10
      : null;
  useEffect(() => {
    if (summary?.avg_city_score != null) {
      prevScoreRef.current = summary.avg_city_score;
    }
  }, [summary?.avg_city_score]);

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      {/* Top nav */}
      <nav className="fixed top-0 left-0 w-full z-50 flex justify-between items-center h-16 px-[24px] bg-surface-container/80 backdrop-blur-md border-b border-outline-variant/20 shadow-sm">
        <div className="flex items-center gap-6">
          <span className="text-[20px] font-bold text-primary tracking-tight font-[DM_Sans]">ResQHub</span>
          <div className="h-6 w-px bg-outline-variant/30" />
          <div className="flex items-center gap-3 text-body-md text-on-surface-variant font-medium">
            <span className="text-primary font-bold border-b-2 border-primary pb-1 flex items-center gap-2 hover:bg-surface-bright/10 hover:text-primary transition-colors cursor-pointer active:scale-95 duration-100">Операційна</span>
            <Link href="/analytics" className="flex items-center gap-2 hover:bg-surface-bright/10 hover:text-primary transition-colors cursor-pointer active:scale-95 duration-100">Аналітика</Link>
            <Link href="/resident" className="flex items-center gap-2 hover:bg-surface-bright/10 hover:text-primary transition-colors cursor-pointer active:scale-95 duration-100">Жителю</Link>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <div className="font-mono text-[14px] text-on-surface-variant bg-surface-container-high px-3 py-1.5 rounded border border-outline-variant/20">
            {clock || "—"}
          </div>
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${wsConnected ? 'bg-secondary animate-pulse-dot' : 'bg-error'}`} />
            <span className="text-xs text-on-surface-variant font-mono">{wsConnected ? 'НАЖИВО' : 'ОФЛАЙН'}</span>
          </div>
          <div className="h-6 w-px bg-outline-variant/30" />
          <button
            onClick={() => handleScenario("BLACKOUT")}
            className="bg-error-container text-on-error-container px-4 py-2 rounded font-bold text-[12px] uppercase tracking-wider hover:bg-error hover:text-on-error transition-colors flex items-center gap-2 glow-red"
          >
            <i className="material-symbols-outlined text-[16px]">warning</i>
            Симулювати блекаут
          </button>
          <button
            onClick={() => handleScenario("RESET")}
            className="border border-outline-variant text-on-surface-variant px-4 py-2 rounded font-bold text-[12px] uppercase tracking-wider hover:bg-surface-container-high hover:text-on-surface transition-colors flex items-center gap-2"
          >
            <i className="material-symbols-outlined text-[16px]">refresh</i>
            Скинути
          </button>
        </div>
      </nav>

      {/* Main three-column grid */}
      <div className="flex flex-1 pt-16 h-screen overflow-hidden animate-fade-in-up">
        {/* Left sidebar — KPIs & resource summary */}
        <aside className="w-[320px] bg-surface-container-low border-r border-outline-variant/20 flex flex-col p-[24px] gap-4 overflow-y-auto shrink-0 hidden md:flex">
          {/* City Resilience Index */}
          <div className="rounded-lg p-[24px] border border-white/5 relative overflow-hidden group bg-[#111827]">
            <div className="absolute -right-12 -top-12 w-32 h-32 bg-secondary/10 rounded-full blur-2xl group-hover:bg-secondary/20 transition-all duration-500" />
            <div className="flex items-center gap-2 mb-4 text-on-surface-variant">
              <i className="material-symbols-outlined text-[20px]">analytics</i>
              <h3 className="font-bold text-[12px] uppercase tracking-wider">Міський індекс стійкості</h3>
            </div>
            <div className="flex items-baseline gap-3">
              <span className="font-[DM_Sans] text-[48px] font-bold leading-none text-on-surface animate-count-up">
                {Math.round(summary?.avg_city_score ?? 0)}
              </span>
              {scoreDelta !== null && Math.abs(scoreDelta) >= 0.1 ? (
                <span
                  className={`font-mono text-[14px] flex items-center px-2 py-0.5 rounded ${
                    scoreDelta > 0
                      ? "text-secondary bg-secondary/10"
                      : "text-error bg-error/10"
                  }`}
                  title={`Зміна відносно попереднього виміру`}
                >
                  <i className="material-symbols-outlined text-[14px] mr-1">
                    {scoreDelta > 0 ? "trending_up" : "trending_down"}
                  </i>
                  {scoreDelta > 0 ? "+" : ""}
                  {scoreDelta.toFixed(1)}
                </span>
              ) : (
                <span className="font-mono text-[12px] text-on-surface-variant/70 bg-surface-container-high px-2 py-0.5 rounded">
                  стабільно
                </span>
              )}
            </div>
            <div className="w-full bg-surface-container-high h-1.5 rounded-full mt-4 overflow-hidden">
              <div
                className="bg-secondary h-full rounded-full transition-all duration-700"
                style={{ width: `${summary?.avg_city_score ?? 0}%` }}
              />
            </div>
          </div>

          {/* Status counters */}
          <div className="grid grid-cols-3 gap-1">
            <StatCard label="Стабіль" value={stable} accent="ok" />
            <StatCard label="Увага" value={warning} accent="warn" />
            <StatCard label="Критичні" value={critical} accent="crit" />
          </div>

          {/* Risk card */}
          <div className="rounded-lg p-[24px] border border-tertiary-container/30 bg-tertiary-container/5 bg-[#111827]">
            <div className="flex items-center gap-2 mb-2 text-tertiary-container">
              <i className="material-symbols-outlined text-[20px]">timer</i>
              <h3 className="font-bold text-[12px] uppercase tracking-wider">Під ризиком &lt; 1 год</h3>
            </div>
            <span className="font-[DM_Sans] text-[48px] font-bold leading-none text-tertiary-container">
              {routing.filter((r) => r.time_to_critical_min !== null && r.time_to_critical_min < 60).length}
            </span>
          </div>

          {/* Resource summary */}
          <div className="rounded-lg p-[24px] border border-white/5 flex-1 flex flex-col bg-[#111827]">
            <div className="flex items-center gap-2 mb-4 text-on-surface-variant">
              <i className="material-symbols-outlined text-[20px]">inventory_2</i>
              <h3 className="font-bold text-[12px] uppercase tracking-wider">Доступні Ресурси</h3>
            </div>
            <div className="flex flex-col gap-3 font-mono text-[14px] text-on-surface">
              <ResourceRow icon="bolt" label="Генератори" count={3} />
              <ResourceRow icon="satellite_alt" label="Starlink" count={2} />
              <ResourceRow icon="engineering" label="Техбригади" count={1} />
              <ResourceRow icon="battery_charging_full" label="Батареї" count={5} />
              <ResourceRow icon="local_gas_station" label="Паливо" count={8} />
            </div>
          </div>
        </aside>

        {/* Center — map + table */}
        <main className="flex-1 flex flex-col relative bg-[#0b0e15]">
          {/* Map area */}
          <div className="flex-1 relative border-b border-outline-variant/20 overflow-hidden">
            <CityMap
              objects={objects}
              selectedId={selectedObjectId}
              onSelect={setSelectedObjectId}
              className="absolute inset-0 h-full w-full z-0"
            />
            <div className="absolute top-[24px] right-[24px] z-[1000]">
              <div className="glass-card rounded-lg p-3 text-xs">
                {activeScenario ? (
                  <span className="text-tertiary font-bold uppercase tracking-wider">
                    ● Активний сценарій: {SCENARIO_TYPE_UA[activeScenario.type] ?? activeScenario.type}
                  </span>
                ) : (
                  <span className="text-secondary font-bold uppercase tracking-wider">
                    ● Нормальна робота
                  </span>
                )}
              </div>
            </div>
          </div>

          {/* Bottom: object table */}
          <div className="h-[40%] bg-surface-container flex flex-col shrink-0">
            <div className="flex justify-between items-center p-4 border-b border-outline-variant/20 bg-[#111827]">
              <div className="flex gap-4 items-center">
                <h2 className="font-semibold text-[20px] text-on-surface">Об&apos;єкти ({total})</h2>
              </div>
            </div>
            <div className="flex-1 overflow-auto bg-[#111827]">
              <ObjectTable objects={objects} onSelect={setSelectedObjectId} selectedId={selectedObjectId} />
            </div>
          </div>
        </main>

        {/* Right sidebar — AI recommendations + log (hidden when drawer open) */}
        <aside className={`w-[360px] bg-surface-container-low border-l border-outline-variant/20 flex-col p-[24px] gap-4 overflow-y-auto shrink-0 hidden xl:flex ${selectedObject ? "hidden" : "flex"}`}>
          <div className="flex-shrink-0">
            <RoutingPanel recommendations={routing} onAssign={handleAssign} />
          </div>
          <div className="w-full h-px bg-outline-variant/20" />
          <div className="flex-shrink-0">
            <EventLog />
          </div>
        </aside>
      </div>

      {/* Drawer — object details (right side; routing panel hidden while open) */}
      {selectedObject && (
        <ObjectDrawer
          object={selectedObject}
          onClose={() => setSelectedObjectId(null)}
          onAssign={handleAssign}
          onBriefing={(id) => setBriefingObjectId(id)}
        />
      )}

      {briefingObjectId && (
        <OperatorBriefingPanel
          objectId={briefingObjectId}
          onClose={() => setBriefingObjectId(null)}
        />
      )}
    </div>
  );
}

function ResourceRow({
  icon,
  label,
  count,
}: {
  icon: string;
  label: string;
  count: number;
}) {
  return (
    <div className="flex justify-between items-center py-2 border-b border-outline-variant/10">
      <span className="flex items-center gap-2">
        <i className="material-symbols-outlined text-outline text-[18px]">{icon}</i>
        {label}
      </span>
      <span className="text-primary font-bold">{count}</span>
    </div>
  );
}

// Таблиця об'єктів —Compact рядок з тими ж полями, як у Stitch
function ObjectTable({
  objects,
  onSelect,
  selectedId,
}: {
  objects: ObjectState[];
  onSelect: (id: string) => void;
  selectedId: string | null;
}) {
  return (
    <table className="w-full text-left border-collapse">
      <thead className="sticky top-0 bg-[#111827] z-10 border-b border-outline-variant/20 uppercase text-[12px] uppercase tracking-wider text-on-surface-variant">
        <tr>
          <th className="py-3 px-4 font-bold">Назва</th>
          <th className="py-3 px-4 font-bold">Тип</th>
          <th className="py-3 px-4 font-bold">Статус</th>
          <th className="py-3 px-4 font-bold">Заряд</th>
          <th className="py-3 px-4 font-bold text-right">Бал</th>
          <th className="py-3 px-4 font-bold text-right">Заповненість</th>
        </tr>
      </thead>
      <tbody className="text-[14px] text-on-surface">
        {objects.map((o, idx) => {
          const status = (o.score?.status ?? "STABLE") as "STABLE" | "WARNING" | "CRITICAL" | "RESCUE_IN_TRANSIT";
          const battery = o.telemetry?.battery_pct ?? 100;
          const score = o.score?.score ?? 100;
          const occ = o.telemetry?.occupancy ?? 0;
          const cap = o.capacity ?? 100;
          const isSel = selectedId === o.id;
          return (
            <tr
              key={o.id}
              onClick={() => onSelect(o.id)}
              className={
                "border-b border-outline-variant/10 hover:bg-surface-bright/10 transition-colors cursor-pointer group" +
                (isSel ? " bg-surface-bright/20" : idx % 2 !== 0 ? " bg-surface-bright/5" : "")
              }
            >
              <td className="py-3 px-4 font-medium group-hover:text-primary transition-colors">{o.name}</td>
              <td className="py-3 px-4 text-on-surface-variant text-xs uppercase tracking-wider">
                {o.type === "SHELTER" ? "Укриття" :
                  o.type === "SCHOOL" ? "Школа" :
                  o.type === "RESILIENCE_POINT" ? "П. Незламн." :
                  o.type === "HOSPITAL" ? "Лікарня" :
                  "Пожежна"}
              </td>
              <td className="py-3 px-4">
                <StatusPill status={status} />
              </td>
              <td className="py-3 px-4">
                <div className="flex items-center gap-2">
                  <div className="w-16 h-1.5 bg-surface-container-high rounded-full overflow-hidden">
                    <div
                      className={battery >= 60 ? "bg-secondary h-full" :
                        battery >= 30 ? "bg-tertiary-container h-full" :
                        "bg-error h-full"}
                      style={{ width: `${battery}%` }}
                    />
                  </div>
                  <span className="font-mono text-[14px] font-medium" style={{
                    color: battery >= 60 ? "#4ae176" : battery >= 30 ? "#df7412" : "#ffb4ab"
                  }}>
                    {Math.round(battery)}%
                  </span>
                </div>
              </td>
              <td className="py-3 px-4 text-right font-mono text-[14px] font-medium">
                {Math.round(score)}
              </td>
              <td className="py-3 px-4 text-right font-mono text-[14px] text-on-surface-variant">
                {occ}/{cap}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

// Слайдер деталей об'єкта
function ObjectDrawer({
  object,
  onClose,
  onAssign,
  onBriefing,
}: {
  object: ObjectState;
  onClose: () => void;
  onAssign: (object_id: string, rt: ResourceTypeT) => Promise<void>;
  onBriefing: (objectId: string) => void;
}) {
  const t = object.telemetry;
  const s = object.score;
  const ttc = s?.time_to_critical_min ?? null;
  const status = (s?.status ?? "STABLE") as "STABLE" | "WARNING" | "CRITICAL" | "RESCUE_IN_TRANSIT";
  const score = s?.score ?? 100;
  const icon = object.type === "SHELTER" ? "shield" :
    object.type === "SCHOOL" ? "school" :
    object.type === "RESILIENCE_POINT" ? "cell_tower" :
    object.type === "HOSPITAL" ? "local_hospital" :
    "fire_truck";
  const statusColorClass =
    status === "STABLE" ? "bg-secondary/20 border-secondary/30 text-secondary" :
    status === "WARNING" ? "bg-tertiary-container/20 border-tertiary/30 text-tertiary" :
    status === "CRITICAL" ? "bg-error-container/20 border-error/30 text-error" :
    "bg-rescue/20 border-rescue/30 text-rescue";
  const resources: ResourceTypeT[] = ["GENERATOR", "BATTERY_BANK", "STARLINK", "TECH_TEAM", "FUEL"];

  const explanation = useMemo(() => {
    if (status === "RESCUE_IN_TRANSIT") {
      return "До об'єкта вже направлено ресурс. Очікуйте прибуття бригади.";
    }
    if (status === "CRITICAL") {
      if (t?.generator_on) return "Критично: генератор працює, але запас палива обмежений. Рекомендується доставка палива.";
      if (t?.power_on === false) return "Критично: зовнішнє живлення відсутнє, батарея майже розряджена. Потрібен генератор або евакуація.";
      if ((t?.battery_pct ?? 100) < 30) return "Критично: низький заряд батареї. Автономність закінчується.";
      return "Критично: показники об'єкта вийшли за безпечні межі.";
    }
    if (status === "WARNING") {
      if (t?.power_on === false && !t?.generator_on) return "Увага: живлення відсутнє, батарея розряджається. Час до критичного стану обмежений.";
      if ((t?.occupancy ?? 0) > object.capacity * 0.8) return "Увага: об'єкт майже заповнений.";
      if ((t?.battery_pct ?? 100) < 50) return "Увага: заряд батареї нижче середнього.";
      return "Увага: є окремі ризики, які потребують моніторингу.";
    }
    return "Стабільно: живлення, зв'язок та ресурси в нормі.";
  }, [status, t, object.capacity]);

  return (
    <aside className="fixed right-0 top-16 h-[calc(100vh-4rem)] w-[26rem] max-w-[calc(100vw-2rem)] z-[60] p-[24px] bg-surface-container-high/95 backdrop-blur-xl border-l border-outline-variant/30 shadow-2xl flex flex-col animate-slide-in-right">
      <div className="flex justify-between items-start mb-6">
        <div>
          <h2 className="text-[20px] font-semibold text-primary mb-1">Деталі об&apos;єкта</h2>
          <p className="text-[14px] text-on-surface-variant">Аналіз телеметрії</p>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => onBriefing(object.id)}
            className="p-2 text-primary hover:bg-primary/10 rounded-full transition-colors"
            title="AI-брифінг для оператора"
            aria-label="AI-брифінг"
          >
            <i className="material-symbols-outlined">auto_awesome</i>
          </button>
          <button
            onClick={onClose}
            className="p-2 text-on-surface-variant hover:text-primary transition-colors bg-surface-container rounded-full"
            aria-label="Закрити"
          >
            <i className="material-symbols-outlined">close</i>
          </button>
        </div>
      </div>
      <div className="flex flex-col gap-6 overflow-y-auto">
        <div className="flex items-center gap-3 border-b border-outline-variant/20 pb-4">
          <div className={`w-12 h-12 rounded-lg flex items-center justify-center border ${statusColorClass}`}>
            <i className="material-symbols-outlined text-[24px]">{icon}</i>
          </div>
          <div>
            <h3 className="text-[20px] font-semibold text-on-surface">{object.name}</h3>
            <StatusPill status={status} />
            <div className="text-xs text-on-surface-variant mt-1">
              {object.district} · {object.address}
            </div>
          </div>
        </div>

        {/* Explanation */}
        <div className={`p-3 rounded-lg border text-[14px] ${
          status === "CRITICAL" ? "bg-error-container/10 border-error/30 text-error" :
          status === "WARNING" ? "bg-tertiary-container/10 border-tertiary/30 text-tertiary" :
          "bg-secondary-container/10 border-secondary/30 text-secondary"
        }`}>
          {explanation}
        </div>

        {/* Telemetry grid */}
        <div className="grid grid-cols-2 gap-3">
          <TelemetryStat label="Заряд" value={`${Math.round(t?.battery_pct ?? 0)}%`} color={batteryColor(t?.battery_pct ?? 0)} />
          <TelemetryStat label="Температура" value={`${t?.temp_c?.toFixed(1) ?? 21}°C`} color="#4ae176" />
          <TelemetryStat label="CO₂" value={`${Math.round(t?.co2_ppm ?? 0)} ppm`} color="#df7412" />
          <TelemetryStat label="Люди" value={`${t?.occupancy ?? 0}/${object.capacity}`} color="#e1e2ec" />
          <TelemetryStat label="Зв'язок" value={t?.internet_on ? "Увімк." : "Вимк."} color={t?.internet_on ? "#4ae176" : "#ffb4ab"} />
          <TelemetryStat label="Генератор" value={t?.generator_on ? "Увімк." : "Вимк."} color={t?.generator_on ? "#4ae176" : "#c2c6d6"} />
        </div>

        {/* Score breakdown */}
        <div className="bg-[#111827] p-4 rounded-lg border border-white/5 flex flex-col gap-4">
          <div className="flex justify-between items-center">
            <h4 className="font-bold text-[12px] uppercase tracking-wider text-on-surface-variant">Бал стійкості</h4>
            <ScoreRing score={score} size={56} thickness={6} />
          </div>
          {s?.components ? (
            <ShapBreakdown components={s.components as Record<string, unknown>} />
          ) : (
            <p className="text-on-surface-variant italic text-[12px]">
              ML-компоненти ще не розраховані
            </p>
          )}
        </div>

        {/* Forecast */}
        {ttc !== null && (
          <div className={`bg-[#111827] p-4 rounded-lg border border-error/30 glow-red${ttc < 30 ? ' glow-pulse' : ''}`}>
            <div className="flex items-center gap-2 text-tertiary-container">
              <i className="material-symbols-outlined">timer</i>
              <h4 className="font-bold text-[12px] uppercase">Прогноз автономності</h4>
            </div>
            <div className="font-mono text-[24px] font-bold mt-1">
              {Math.round(ttc)} хв до критичного
            </div>
          </div>
        )}

        {/* Resource buttons */}
        <div>
          <h4 className="font-bold text-[12px] uppercase tracking-wider text-on-surface-variant mb-3">
            Направити ресурс
          </h4>
          <div className="grid grid-cols-2 gap-2">
            {resources.map((rt) => (
              <button
                key={rt}
                onClick={() => onAssign(object.id, rt)}
                className="bg-primary/10 text-primary hover:bg-primary hover:text-on-primary border border-primary/30 px-3 py-2 rounded font-bold text-[12px] uppercase tracking-wider transition-colors"
              >
                {rt === "GENERATOR" ? "Генератор" :
                  rt === "BATTERY_BANK" ? "Батарея" :
                  rt === "STARLINK" ? "Starlink" :
                  rt === "TECH_TEAM" ? "Техбригада" :
                  "Паливо"}
              </button>
            ))}
          </div>
        </div>
      </div>
    </aside>
  );
}

function TelemetryStat({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="bg-[#111827] p-3 rounded-lg border border-white/5 flex flex-col gap-1">
      <span className="font-bold text-[12px] uppercase tracking-wider text-on-surface-variant">{label}</span>
      <span className="font-mono text-[24px] font-semibold" style={{ color }}>{value}</span>
    </div>
  );
}

function batteryColor(b: number): string {
  return b >= 60 ? "#4ae176" : b >= 30 ? "#df7412" : "#ffb4ab";
}