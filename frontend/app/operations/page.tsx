"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { RealtimeProvider } from "@/components/RealtimeProvider";
import { useStore } from "@/lib/store";
import { api } from "@/lib/api";
import { CityMap, type RescueVehicle } from "@/components/CityMap";
import { EventLog } from "@/components/EventLog";
import { StatCard } from "@/components/StatCard";
import { ToastContainer, pushToast } from "@/components/Toast";
import { HeaderActions } from "@/components/HeaderActions";
import { StatusPill } from "@/components/ui/StatusPill";
import { RESOURCE_TYPE_UA, SCENARIO_TYPE_UA } from "@/lib/types";
import Link from "next/link";
import type { ObjectState, ResourceTypeT } from "@/lib/types";
import { buildOperatorBrief } from "@/lib/recommendations";

// ── Парк техніки та логістика ────────────────────────────────────────
const DEPOT: [number, number] = [50.255, 28.65];
const FLEET: Record<string, number> = {
  GENERATOR: 3,
  STARLINK: 2,
  TECH_TEAM: 2,
  BATTERY_BANK: 5,
  FUEL: 8,
};
// Консумативні ресурси лишаються на об'єкті (не повертаються у парк).
// TECH_TEAM — повертається після роботи.
const CONSUMABLE = new Set(["GENERATOR", "STARLINK", "BATTERY_BANK", "FUEL"]);

const ANIM_OUT_MS = 6000; // виїзд
const ANIM_BACK_MS = 5000; // повернення
const WORK_MS = 4000; // техбригада «працює» на місці

// Маршрут по РЕАЛЬНИХ дорогах через OSRM. Fallback — пряма лінія, тож
// анімація ніколи не ламається (навіть офлайн).
async function fetchRoad(
  from: [number, number],
  to: [number, number]
): Promise<[number, number][]> {
  try {
    const url =
      `https://router.project-osrm.org/route/v1/driving/` +
      `${from[1]},${from[0]};${to[1]},${to[0]}?overview=full&geometries=geojson`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(String(res.status));
    const data = await res.json();
    const coords = data?.routes?.[0]?.geometry?.coordinates;
    if (Array.isArray(coords) && coords.length > 1) {
      // OSRM віддає [lon,lat] → перевертаємо у [lat,lon]
      return coords.map((c: [number, number]) => [c[1], c[0]] as [number, number]);
    }
  } catch {
    /* fallback нижче */
  }
  return [from, to];
}

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
    assignments,
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

  // Активні анімаційні машини на карті
  const [vehicles, setVehicles] = useState<RescueVehicle[]>([]);
  const knownVehiclesRef = useRef<Set<string>>(new Set());

  // Доступність ресурсів: парк мінус ті, що «зайняті».
  // Консумативні (генератор/паливо/батарея/Starlink) лишаються на об'єкті
  // назавжди; техбригада повертається → звільняє одиницю.
  const [committed, setCommitted] = useState<Record<string, number>>({});
  const availableResources = useMemo(() => {
    const out: Record<string, number> = {};
    for (const k of Object.keys(FLEET)) {
      out[k] = Math.max(0, FLEET[k] - (committed[k] || 0));
    }
    return out;
  }, [committed]);

  // Коли грід повертається (сценарій завершився) — техніку поповнюємо.
  useEffect(() => {
    if (!activeScenario) setCommitted({});
  }, [activeScenario]);

  // Нове assignment → машина виїжджає по дорогах.
  useEffect(() => {
    if (!assignments.length) return;
    const known = knownVehiclesRef.current;
    const fresh = assignments.filter(
      (a) => !known.has(a.id) && a.status === "DISPATCHED"
    );
    if (!fresh.length) return;
    fresh.forEach((a) => known.add(a.id));

    fresh.forEach(async (a) => {
      const target = objects.find((o) => o.id === a.object_id);
      if (!target) return;
      const label = RESOURCE_TYPE_UA[a.resource_type] ?? a.resource_type;
      const dest: [number, number] = [target.lat, target.lon];
      const isTechTeam = a.resource_type === "TECH_TEAM";

      // Ресурс виїхав → доступних стає менше
      setCommitted((c) => ({
        ...c,
        [a.resource_type]: (c[a.resource_type] || 0) + 1,
      }));

      const road = await fetchRoad(DEPOT, dest);
      const back = [...road].reverse();
      const outId = `out-${a.id}`;
      const workId = `work-${a.id}`;
      const backId = `back-${a.id}`;
      const addVehicle = (v: RescueVehicle) =>
        setVehicles((cur) => (cur.some((x) => x.id === v.id) ? cur : [...cur, v]));
      const rm = (id: string) =>
        setVehicles((cur) => cur.filter((v) => v.id !== id));

      // ВАЖЛИВО: життєвий цикл керується setTimeout, а не rAF-onComplete.
      // rAF (плавний рух) призупиняється у фоновій вкладці, тож завершення
      // доставки не мало б залежати від нього — інакше при перемиканні
      // вкладки об'єкт «завис би в дорозі».
      const now = performance.now();
      addVehicle({
        id: outId,
        path: road,
        startMs: now,
        endMs: now + ANIM_OUT_MS,
        kind: "outbound",
        label,
      });

      // Прибуття → ефект + повернення/робота
      setTimeout(() => {
        rm(outId);
        api
          .completeAssignment(a.id, "success")
          .then(() =>
            pushToast(
              `${label} прибув на ${target.name}. Об'єкт відновлюється.`,
              "success"
            )
          )
          .catch((err) => console.error("[completeAssignment] failed:", err));

        const spawnReturn = () => {
          const rs = performance.now();
          addVehicle({
            id: backId,
            path: back,
            startMs: rs,
            endMs: rs + ANIM_BACK_MS,
            kind: "inbound",
            label: "↩ на базу",
          });
          setTimeout(() => {
            rm(backId);
            known.delete(a.id);
            // Техбригада повернулась → одиниця знову доступна.
            // Консумативи лишаються витраченими на об'єкті.
            if (isTechTeam) {
              setCommitted((c) => ({
                ...c,
                TECH_TEAM: Math.max(0, (c.TECH_TEAM || 0) - 1),
              }));
            }
          }, ANIM_BACK_MS);
        };

        if (isTechTeam) {
          // Техбригада ПРАЦЮЄ на місці кілька секунд, потім повертається
          const ws = performance.now();
          addVehicle({
            id: workId,
            path: [dest],
            startMs: ws,
            endMs: ws + WORK_MS,
            kind: "working",
            label: "🔧 працює",
          });
          setTimeout(() => {
            rm(workId);
            spawnReturn();
          }, WORK_MS);
        } else {
          spawnReturn();
        }
      }, ANIM_OUT_MS);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assignments, objects]);

  async function handleScenario(type: "BLACKOUT" | "RESET" | "SIGNAL_DOWN" | "PARTIAL_OUTAGE") {
    try {
      const sc = await api.startScenario(type, "CITY", null, 1.0);
      const names: Record<string, string> = {
        BLACKOUT: "Блекаут",
        RESET: "Скидання",
        SIGNAL_DOWN: "Зв'язок відсутній",
        PARTIAL_OUTAGE: "Часткове відключення",
      };
      if (type === "RESET") {
        pushToast("Скинуто: повернення до нормального режиму", "success");
      } else if (sc) {
        pushToast(`Сценарій «${names[type]}» активовано`, "warning");
      }
    } catch (e) {
      console.error(e);
      pushToast("Помилка запуску сценарію", "error");
    }
  }

  async function handleAssign(object_id: string, resource_type: ResourceTypeT) {
    try {
      const target = objects.find((o) => o.id === object_id);
      await api.createAssignment(object_id, resource_type);
      pushToast(
        `${RESOURCE_TYPE_UA[resource_type]} вирушив до ${target?.name ?? "об'єкта"}`,
        "info",
      );
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
              <span
                className="material-symbols-outlined text-on-surface-variant text-[14px] cursor-help"
                title="Середній Бал стійкості по всіх об'єктах міста (0–100). Падіння означає, що ML-модель бачить погіршення умов: розряд батарей, відсутність живлення, перегрів, перевищення CO₂ або критичну заповненість."
                aria-label="Що таке Міський індекс стійкості"
              >
                info
              </span>
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
              <ResourceRow icon="bolt" label="Генератори" count={availableResources.GENERATOR} />
              <ResourceRow icon="satellite_alt" label="Starlink" count={availableResources.STARLINK} />
              <ResourceRow icon="engineering" label="Техбригади" count={availableResources.TECH_TEAM} />
              <ResourceRow icon="battery_charging_full" label="Батареї" count={availableResources.BATTERY_BANK} />
              <ResourceRow icon="local_gas_station" label="Паливо" count={availableResources.FUEL} />
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
              rescueVehicles={vehicles}
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

        {/* Right sidebar — event log (hidden when drawer open) */}
        <aside className={`w-[360px] bg-surface-container-low border-l border-outline-variant/20 flex-col p-[24px] gap-4 overflow-y-auto shrink-0 hidden xl:flex ${selectedObject ? "hidden" : "flex"}`}>
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
}: {
  object: ObjectState;
  onClose: () => void;
  onAssign: (object_id: string, rt: ResourceTypeT) => Promise<void>;
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

  const brief = useMemo(
    () => buildOperatorBrief(object, s ?? null, t ?? null),
    [object, s, t],
  );

  const briefUrgencyClass = {
    ok: "bg-secondary/10 border-secondary/30 text-secondary",
    watch: "bg-tertiary-container/10 border-tertiary/30 text-tertiary",
    act: "bg-tertiary-container/20 border-tertiary/40 text-tertiary",
    critical: "bg-error-container/20 border-error/40 text-error",
  }[brief.urgency];

  return (
    <aside className="fixed right-0 top-16 h-[calc(100vh-4rem)] w-[26rem] max-w-[calc(100vw-2rem)] z-[60] p-[24px] bg-surface-container-high/95 backdrop-blur-xl border-l border-outline-variant/30 shadow-2xl flex flex-col animate-slide-in-right">
      <div className="flex justify-between items-start mb-6">
        <div>
          <h2 className="text-[20px] font-semibold text-primary mb-1">Деталі об&apos;єкта</h2>
          <p className="text-[14px] text-on-surface-variant">Аналіз телеметрії</p>
        </div>
        <div className="flex items-center gap-1">
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
        <div
          className={`p-3 rounded-lg border text-[14px] ${
            status === "RESCUE_IN_TRANSIT"
              ? "bg-rescue/10 border-rescue/30 text-rescue"
              : status === "CRITICAL"
                ? "bg-error-container/10 border-error/30 text-error"
                : status === "WARNING"
                  ? "bg-tertiary-container/10 border-tertiary/30 text-tertiary"
                  : "bg-secondary-container/10 border-secondary/30 text-secondary"
          }`}
          data-testid="object-explanation"
        >
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

        {/* Operator brief — проста людинo-читабельна порада */}
        <div
          className={`p-4 rounded-lg border flex flex-col gap-3 ${briefUrgencyClass}`}
          data-testid="operator-brief"
        >
          <div className="flex items-start gap-3">
            <i className="material-symbols-outlined text-[24px]">
              {brief.urgency === "ok" ? "check_circle"
                : brief.urgency === "watch" ? "visibility"
                : brief.urgency === "act" ? "build"
                : "warning"}
            </i>
            <div className="flex-1">
              <div className="text-[10px] font-bold uppercase tracking-wider opacity-70 mb-0.5">
                {brief.urgency === "ok" ? "Все добре" : "Рекомендація диспетчеру"}
              </div>
              <div className="font-bold text-[16px] leading-tight mb-1">
                {brief.headline}
              </div>
              <div className="text-[14px] leading-snug">
                {brief.recommendation}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2 text-[12px] opacity-80 border-t border-white/10 pt-2">
            <i className="material-symbols-outlined text-[16px]">schedule</i>
            <span className="font-mono">{brief.forecast}</span>
          </div>
          {brief.suggestedResource &&
            brief.suggestedResource !== "EVACUATION" &&
            status !== "RESCUE_IN_TRANSIT" && (
              <button
                onClick={() =>
                  onAssign(object.id, brief.suggestedResource as ResourceTypeT)
                }
                className="bg-primary text-on-primary font-semibold text-[14px] py-2.5 rounded-lg hover:bg-primary-container hover:text-on-primary-container transition-colors flex items-center justify-center gap-2 active:scale-95"
              >
                <i className="material-symbols-outlined text-[18px]">local_shipping</i>
                Направити {RESOURCE_TYPE_UA[brief.suggestedResource as ResourceTypeT]} одразу
              </button>
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
        {status === "RESCUE_IN_TRANSIT" ? (
          <div
            className="bg-rescue/10 border border-rescue/30 rounded-lg p-4 flex items-center gap-3"
            data-testid="resource-in-transit"
          >
            <i className="material-symbols-outlined text-rescue text-[28px]">local_shipping</i>
            <div>
              <div className="font-bold text-[14px] text-rescue uppercase tracking-wider">
                Ресурс у дорозі
              </div>
              <div className="text-[12px] text-on-surface-variant mt-0.5">
                Допомога вже направлена. Очікуйте прибуття бригади.
              </div>
            </div>
          </div>
        ) : (
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
        )}
      </div>
    </aside>
  );
}

const TELEMETRY_HINTS: Record<string, string> = {
  "Заряд": "Залишок заряду батареї об'єкта. Нижче 30% — критично, без зовнішнього живлення об'єкт вимкнеться через ~1 год.",
  "Температура": "Температура всередині приміщення. Норма 18-25°C. Вище 28°C — дискомфорт, потрібна вентиляція.",
  "CO₂": "Рівень вуглекислого газу (ppm). Норма <800. 1000-1500 — задуха, сонливість. >2000 — небезпечно, потрібна негайна вентиляція. Вимірюється датчиком якості повітря.",
  "Люди": "Поточна кількість людей / максимальна місткість. Якщо >90% — переповнення, ризик паніки та проблем з повітрям.",
  "Зв'язок": "Стан інтернет-з'єднання. Залежить від Starlink (якщо є на об'єкті) або звичайного провайдера. Без зв'язку диспетчер не може бачити реальний час телеметрії.",
  "Генератор": "Чи увімкнений резервний генератор. На реальному об'єкті вмикається бригадою вручну після доставки пального.",
};

function TelemetryStat({ label, value, color }: { label: string; value: string; color: string }) {
  const hint = TELEMETRY_HINTS[label];
  return (
    <div className="bg-[#111827] p-3 rounded-lg border border-white/5 flex flex-col gap-1">
      <div className="flex items-center gap-1.5">
        <span className="font-bold text-[12px] uppercase tracking-wider text-on-surface-variant">{label}</span>
        {hint && (
          <span
            className="material-symbols-outlined text-on-surface-variant text-[12px] cursor-help"
            title={hint}
            aria-label={`Що таке ${label}`}
          >
            info
          </span>
        )}
      </div>
      <span className="font-mono text-[24px] font-semibold" style={{ color }}>{value}</span>
    </div>
  );
}

function batteryColor(b: number): string {
  return b >= 60 ? "#4ae176" : b >= 30 ? "#df7412" : "#ffb4ab";
}