"use client";

import { useEffect, useState } from "react";
import { RealtimeProvider } from "@/components/RealtimeProvider";
import { HeaderActions } from "@/components/HeaderActions";
import { MobileNav } from "@/components/MobileNav";
import { useStore } from "@/lib/store";
import { api } from "@/lib/api";
import Link from "next/link";
import type { BoltEvent } from "@/lib/types";

export default function AnalyticsPage() {
  return (
    <RealtimeProvider>
      <AnalyticsShell />
    </RealtimeProvider>
  );
}

const severityStyle: Record<string, { dotClass: string; textClass: string; icon: string }> = {
  INFO: { dotClass: "bg-on-surface-variant", textClass: "text-on-surface-variant", icon: "info" },
  WARNING: { dotClass: "bg-tertiary-container", textClass: "text-tertiary", icon: "warning" },
  ERROR: { dotClass: "bg-error", textClass: "text-error", icon: "error" },
};

function relativeTime(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime();
  const sec = Math.floor(diff / 1000);
  if (sec < 60) return `${sec} с тому`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min} хв тому`;
  const hr = Math.floor(min / 60);
  return `${hr} год тому`;
}

function AnalyticsShell() {
  const { summary, objects } = useStore();
  const [forecast, setForecast] = useState<HistoricalData[]>([]);
  // Діапазон часу для графіка (хв). SESSION = уся зібрана історія сесії.
  const [rangeMin, setRangeMin] = useState<number>(60);
  // Аналітика тримає ПОВНУ історію подій (незалежно від оперативного
  // журналу на операційній сторінці, який очищається).
  const [history, setHistory] = useState<BoltEvent[]>([]);

  useEffect(() => {
    let cancelled = false;
    async function loadHistory() {
      try {
        const data = await api.events(50);
        if (!cancelled && Array.isArray(data)) setHistory(data as BoltEvent[]);
      } catch (e) {
        console.error("[analytics] events history failed:", e);
      }
    }
    loadHistory();
    const interval = setInterval(loadHistory, 10000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  // Реальний тренд: тягнемо scores для всіх об'єктів та агрегуємо
  useEffect(() => {
    let cancelled = false;
    async function load() {
      if (objects.length === 0) return;
      try {
        // Бакетуємо бали ПО ХВИЛИНІ через ВСІ об'єкти. Раніше ключем був
        // точний timestamp — а вони в об'єктів не збігаються, тож кожна
        // «точка» була балом одного об'єкта → шумна беззмістовна крива.
        // Тепер кожна точка = середній бал міста за цю хвилину.
        // Скільки рядків score тягнути під обраний діапазон (12 тіків/хв).
        const fetchLimit = rangeMin >= 100000 ? 500 : Math.min(500, rangeMin * 12 + 12);
        const bucket: Record<number, number[]> = {};
        await Promise.all(
          objects.map(async (o) => {
            try {
              const scores = await api.scores(o.id, fetchLimit);
              for (const s of scores) {
                const minute = Math.floor(new Date(s.ts).getTime() / 60000);
                (bucket[minute] ??= []).push(s.score);
              }
            } catch {
              /* ignore */
            }
          }),
        );
        if (cancelled) return;
        const data: HistoricalData[] = Object.entries(bucket)
          .map(([minute, scores]) => ({
            t: new Date(Number(minute) * 60000),
            value: scores.reduce((a, b) => a + b, 0) / scores.length,
          }))
          .filter(
            (d) => rangeMin >= 100000 || d.t.getTime() >= Date.now() - rangeMin * 60000,
          )
          .sort((a, b) => a.t.getTime() - b.t.getTime())
          .slice(-80);
        setForecast(data);
      } catch (e) {
        console.error("[analytics] trend load failed:", e);
      }
    }
    load();
    const interval = setInterval(load, 10000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [objects, rangeMin]);

  const districts = Array.from(new Set(objects.map((o) => o.district)));
  const districtStats = districts.map((d) => {
    const objs = objects.filter((o) => o.district === d);
    const scores = objs.map((o) => o.score?.score ?? 100);
    const avg = scores.reduce((a, b) => a + b, 0) / Math.max(1, scores.length);
    const criticalCount = objs.filter((o) => o.score?.status === "CRITICAL").length;
    const warningCount = objs.filter((o) => o.score?.status === "WARNING").length;
    const ttcs = objs
      .map((o) => o.score?.time_to_critical_min)
      .filter((t): t is number => t != null && t > 0);
    const minTtc = ttcs.length > 0 ? Math.min(...ttcs) : null;
    const powerOnCount = objs.filter(
      (o) => o.telemetry?.power_on || o.telemetry?.generator_on
    ).length;
    return {
      district: d,
      avg: Math.round(avg),
      critical: criticalCount,
      warning: warningCount,
      total: objs.length,
      minTtc,
      powerOnCount,
    };
  });

  const stablePercent = ((summary?.stable ?? 0) / Math.max(1, summary?.total_objects ?? 10)) * 100;
  const warningPercent = ((summary?.warning ?? 0) / Math.max(1, summary?.total_objects ?? 10)) * 100;
  const criticalPercent = ((summary?.critical ?? 0) / Math.max(1, summary?.total_objects ?? 10)) * 100;
  const rescuePercent = ((summary?.rescue_in_transit ?? 0) / Math.max(1, summary?.total_objects ?? 10)) * 100;

  // Реальні метрики доступності замість хардкоду
  // «З живленням» = мережа або працюючий генератор
  const powerOnlinePct = objects.length > 0
    ? Math.round(
        (objects.filter((o) => o.telemetry?.power_on || o.telemetry?.generator_on)
          .length /
          objects.length) *
          100
      )
    : 0;
  const internetOnlinePct = objects.length > 0
    ? Math.round((objects.filter((o) => o.telemetry?.internet_on).length / objects.length) * 100)
    : 0;
  const generatorCoveragePct = objects.length > 0
    ? Math.round((objects.filter((o) => o.telemetry?.generator_on).length / objects.length) * 100)
    : 0;
  const autonomyUnder1h = objects.filter(
    (o) => o.score?.time_to_critical_min != null && o.score.time_to_critical_min < 60,
  ).length;

  const stableAngle = stablePercent;
  const warningAngle = stableAngle + warningPercent;
  const criticalAngle = warningAngle + criticalPercent;
  
  const donutGradient = `conic-gradient(#4ae176 0% ${stableAngle}%, #df7412 ${stableAngle}% ${warningAngle}%, #ffb4ab ${warningAngle}% ${criticalAngle}%, #9b59b6 ${criticalAngle}% 100%)`;

  return (
    <div className="flex flex-col min-h-screen bg-grid animate-fade-in-up">
      {/* Top nav */}
      <nav className="fixed top-0 left-0 w-full z-50 flex justify-between items-center h-16 px-[24px] bg-surface-container/80 backdrop-blur-md border-b border-outline-variant/20 shadow-sm">
        <div className="flex items-center gap-6">
          <span className="text-[20px] font-bold text-primary tracking-tight font-[DM_Sans]">ResQHub</span>
          <div className="hidden sm:block h-6 w-px bg-outline-variant/30" />
          <div className="hidden sm:flex items-center gap-3 text-body-md text-on-surface-variant font-medium">
            <Link href="/operations" className="flex items-center gap-2 hover:bg-surface-bright/10 hover:text-primary transition-colors cursor-pointer active:scale-95 duration-100">Операційна</Link>
            <span className="text-primary font-bold border-b-2 border-primary pb-1 flex items-center gap-2 hover:bg-surface-bright/10 hover:text-primary transition-colors cursor-pointer active:scale-95 duration-100">Аналітика</span>
            <Link href="/resident" className="flex items-center gap-2 hover:bg-surface-bright/10 hover:text-primary transition-colors cursor-pointer active:scale-95 duration-100">Жителю</Link>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <HeaderActions />
        </div>
      </nav>

      {/* Main */}
      <main className="flex-1 pt-24 pb-24 md:pb-8 px-4 md:px-[32px] overflow-y-auto">
        <header className="mb-8 flex flex-col md:flex-row md:justify-between md:items-end gap-4">
          <div>
            <h2 className="text-[32px] font-semibold text-on-surface tracking-tight font-[DM_Sans]">
              Аналітика та тренди міської стійкості
            </h2>
            <p className="text-[16px] text-on-surface-variant mt-2 max-w-2xl">
              Телеметрія в реальному часі та прогнозні моделі для інфраструктури Житомира.
            </p>
          </div>
          <div className="flex flex-wrap gap-3">
            <div className="flex rounded-lg border border-outline-variant/30 glass-card overflow-hidden">
              {[
                { min: 15, label: "15 хв" },
                { min: 60, label: "1 год" },
                { min: 100000, label: "Сесія" },
              ].map((r) => (
                <button
                  key={r.min}
                  onClick={() => setRangeMin(r.min)}
                  className={`px-3 py-2 text-[13px] transition-colors ${
                    rangeMin === r.min
                      ? "bg-primary-container/20 text-primary font-semibold"
                      : "text-on-surface-variant hover:bg-surface-bright/20"
                  }`}
                >
                  {r.label}
                </button>
              ))}
            </div>
            <Link href="/operations" className="px-4 py-2 rounded-lg bg-primary-container/10 border border-primary text-primary text-[14px] hover:bg-primary-container/20 glow-blue flex items-center gap-2">
              <i className="material-symbols-outlined text-[18px]">dashboard</i>
              <span className="hidden sm:inline">До операційної</span>
            </Link>
          </div>
        </header>

        {/* KPIs */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
          <KpiCard
            title="Середній індекс стійкості"
            icon="security"
            iconColor="text-primary"
            value={`${Math.round(summary?.avg_city_score ?? 0)}`}
            trend={(summary?.avg_city_score ?? 0) > 75 ? "up" : "down"}
            trendValue={`${(Math.round(summary?.avg_city_score ?? 0) - 74) > 0 ? "+" : ""}${Math.round(summary?.avg_city_score ?? 0) - 74}%`}
          />
          <KpiCard
            title="Доступність живлення"
            icon="bolt"
            iconColor={powerOnlinePct >= 80 ? "text-secondary" : "text-error"}
            value={`${powerOnlinePct}%`}
            trend={powerOnlinePct >= 80 ? "stable" : "down"}
            trendValue={`${powerOnlinePct}/${objects.length || 0} об'єктів`}
          />
          <KpiCard
            title="Критичні інциденти"
            icon="warning"
            iconColor="text-error"
            value={`${(summary?.critical ?? 0) + (summary?.rescue_in_transit ?? 0)}`}
            trend={(summary?.critical ?? 0) > 0 ? "down" : "stable"}
            trendValue={
              (summary?.rescue_in_transit ?? 0) > 0
                ? `${summary?.rescue_in_transit} бригад у дорозі`
                : "Без ескалацій"
            }
          />
        </div>

        {/* Trend chart */}
        <div className="glass-card rounded-xl p-[24px] mb-8">
          <div className="flex justify-between items-start mb-6 border-b border-outline-variant/20 pb-4">
            <div className="flex items-start gap-3">
              <i className="material-symbols-outlined text-primary mt-1">timeline</i>
              <div>
                <h3 className="text-[20px] font-semibold text-on-surface">Динаміка індексу стійкості міста</h3>
                <p className="text-[13px] text-on-surface-variant mt-1 max-w-xl">
                  Середній бал усіх об'єктів по хвилинах. Падіння лінії = блекаут або
                  деградація, підйом = відновлення й прибуття ресурсів.
                </p>
              </div>
            </div>
            <div className="text-right flex-shrink-0">
              <div className="font-mono text-[28px] font-bold text-primary leading-none">
                {Math.round(summary?.avg_city_score ?? 0)}
              </div>
              <div className="text-[11px] uppercase tracking-wider text-on-surface-variant mt-1">зараз</div>
            </div>
          </div>
          <div className="h-64 w-full relative bg-surface-dim/30 rounded-lg border border-outline-variant/10 overflow-hidden">
            {/* Horizontal reference lines */}
            <div className="absolute left-0 right-0 w-full border-t border-secondary/30" style={{ top: '30%' }}></div>
            <div className="absolute left-0 right-0 w-full border-t border-tertiary/30" style={{ top: '60%' }}></div>
            
            <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="w-full h-full absolute bottom-0 left-0">
              <defs>
                <linearGradient id="fade" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0" stopColor="#4d8eff" stopOpacity="0.4" />
                  <stop offset="1" stopColor="#4d8eff" stopOpacity="0" />
                </linearGradient>
                <filter id="glow">
                  <feGaussianBlur stdDeviation="1.5" result="coloredBlur"/>
                  <feMerge>
                    <feMergeNode in="coloredBlur"/>
                    <feMergeNode in="SourceGraphic"/>
                  </feMerge>
                </filter>
              </defs>
              {forecast.length > 1 && (
                <>
                  <path
                    d={fillPath(forecast.map((p) => p.value))}
                    fill="url(#fade)"
                    stroke="none"
                  />
                  <path
                    d={linePath(forecast.map((p) => p.value))}
                    fill="none"
                    stroke="#4d8eff"
                    strokeWidth="1.5"
                    filter="url(#glow)"
                  />
                  {/* Data points */}
                  {forecast.map((p, i) => {
                    const max = 100;
                    const min = 0;
                    const step = 100 / (forecast.length - 1);
                    const x = i * step;
                    const y = 100 - ((p.value - min) / (max - min)) * 100;
                    return (
                      <circle key={i} cx={x} cy={y} r="0.8" fill="#fff" stroke="#4d8eff" strokeWidth="0.4" />
                    );
                  })}
                </>
              )}
            </svg>
            {/* Y-axis scale labels */}
            <div className="absolute text-[10px] text-on-surface-variant font-mono" style={{ top: '2px', right: '6px' }}>100</div>
            <div className="absolute text-[10px] text-secondary font-mono" style={{ top: 'calc(30% - 14px)', left: '4px' }}>Стабільно (70)</div>
            <div className="absolute text-[10px] text-tertiary font-mono" style={{ top: 'calc(60% - 14px)', left: '4px' }}>Увага (40)</div>
            <div className="absolute text-[10px] text-on-surface-variant font-mono" style={{ bottom: '2px', right: '6px' }}>0</div>

            {/* Empty state — поки немає історії */}
            {forecast.length <= 1 && (
              <div className="absolute inset-0 flex items-center justify-center text-center px-6">
                <div className="text-on-surface-variant text-[13px]">
                  <i className="material-symbols-outlined text-[28px] opacity-40 block mb-1">timeline</i>
                  Збираємо телеметрію… Графік з'явиться за хвилину роботи симулятора.<br/>
                  Запусти блекаут — і лінія піде вниз у реальному часі.
                </div>
              </div>
            )}
          </div>

          {/* X-axis time labels */}
          {forecast.length > 1 && (
            <div className="flex justify-between mt-2 px-1 font-mono text-[10px] text-on-surface-variant">
              <span>{forecast[0].t.toLocaleTimeString("uk-UA", { hour: "2-digit", minute: "2-digit" })}</span>
              <span>{forecast[Math.floor(forecast.length / 2)].t.toLocaleTimeString("uk-UA", { hour: "2-digit", minute: "2-digit" })}</span>
              <span>{forecast[forecast.length - 1].t.toLocaleTimeString("uk-UA", { hour: "2-digit", minute: "2-digit" })}</span>
            </div>
          )}
        </div>

        {/* Split row */}
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-6 mb-8">
          {/* Left: metrics bars */}
          <div className="glass-card rounded-xl p-[24px] lg:col-span-3">
            <div className="flex items-center gap-3 mb-6 border-b border-outline-variant/20 pb-4">
              <i className="material-symbols-outlined text-secondary">power</i>
              <h3 className="text-[20px] font-semibold text-on-surface">Доступність критичних мереж</h3>
            </div>
            <div className="space-y-4">
              <ProgressBar
                label="Живлення"
                value={powerOnlinePct}
                color={powerOnlinePct >= 80 ? "secondary" : powerOnlinePct >= 50 ? "tertiary" : "error"}
                glow={powerOnlinePct < 50 ? "glow-red" : undefined}
              />
              <ProgressBar
                label="Зв'язок (Starlink/інтернет)"
                value={internetOnlinePct}
                color={internetOnlinePct >= 80 ? "primary" : internetOnlinePct >= 50 ? "tertiary" : "error"}
                glow={internetOnlinePct >= 80 ? "glow-blue" : undefined}
              />
              <ProgressBar
                label="Резерв генераторів"
                value={generatorCoveragePct}
                color={generatorCoveragePct >= 50 ? "secondary" : generatorCoveragePct >= 25 ? "tertiary" : "error"}
              />
              <ProgressBar
                label="Під ризиком <1 год"
                value={autonomyUnder1h === 0 ? 100 : Math.max(0, 100 - autonomyUnder1h * 20)}
                color={autonomyUnder1h === 0 ? "secondary" : "error"}
                glow={autonomyUnder1h > 0 ? "glow-red" : undefined}
                suffix={autonomyUnder1h > 0 ? `${autonomyUnder1h} об'єктів` : "немає"}
              />
            </div>
          </div>

          {/* Right: donut */}
          <div className="glass-card rounded-xl p-[24px] lg:col-span-2 flex flex-col">
            <div className="flex items-center gap-3 mb-6 border-b border-outline-variant/20 pb-4">
              <i className="material-symbols-outlined text-tertiary">pie_chart</i>
              <h3 className="text-[20px] font-semibold text-on-surface">Розподіл інцидентів</h3>
            </div>
            <div className="flex-1 flex flex-col md:flex-row items-center justify-center gap-8 relative min-h-[150px]">
              <div className="w-32 h-32 rounded-full border-[16px] border-surface-bright/20 relative flex-shrink-0">
                <div
                  className="absolute inset-[-16px] rounded-full opacity-80"
                  style={{
                    background: donutGradient,
                    mask: "radial-gradient(transparent 55%, black 56%)",
                    WebkitMask: "radial-gradient(transparent 55%, black 56%)",
                  }}
                />
                <div className="absolute inset-0 flex items-center justify-center flex-col">
                  <span className="font-mono text-xl font-bold text-on-surface">{summary?.total_objects ?? 10}</span>
                  <span className="font-bold text-[10px] uppercase text-on-surface-variant">Об&apos;єктів</span>
                </div>
              </div>
              
              <div className="flex flex-col gap-2 mt-4 md:mt-0">
                <div className="flex items-center gap-2 text-xs">
                  <span className="w-3 h-3 rounded-full bg-secondary" /> Стабільні ({summary?.stable ?? 0})
                </div>
                <div className="flex items-center gap-2 text-xs">
                  <span className="w-3 h-3 rounded-full bg-tertiary" /> Увага ({summary?.warning ?? 0})
                </div>
                <div className="flex items-center gap-2 text-xs">
                  <span className="w-3 h-3 rounded-full bg-error" /> Критичні ({summary?.critical ?? 0})
                </div>
                {(summary?.rescue_in_transit ?? 0) > 0 && (
                  <div className="flex items-center gap-2 text-xs">
                    <span className="w-3 h-3 rounded-full bg-[#9b59b6]" /> Доп. їде ({summary?.rescue_in_transit ?? 0})
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Autonomy forecast by district */}
        <div className="glass-card rounded-xl p-[24px] mb-8">
          <div className="flex items-center gap-3 mb-6 border-b border-outline-variant/20 pb-4">
            <i className="material-symbols-outlined text-inverse-primary">hourglass_empty</i>
            <h3 className="text-[20px] font-semibold text-on-surface">Прогноз автономності по районах</h3>
            <span className="ml-auto font-mono text-xs text-on-surface-variant bg-surface-bright/20 px-2 py-1 rounded">За поточного навантаження</span>
          </div>
          <div className="space-y-6">
            {districtStats.map((d) => {
              const barColor = d.avg >= 70 ? 'bg-secondary' : d.avg >= 40 ? 'bg-tertiary' : 'bg-error';
              const textColor = d.avg >= 70 ? 'text-secondary' : d.avg >= 40 ? 'text-tertiary' : 'text-error';
              const forecastLabel = d.critical > 0
                ? <span className="text-error">⚠ {d.critical} критичних, потрібна евакуація</span>
                : d.minTtc != null && d.minTtc < 60
                  ? <span className="text-tertiary">⏱ Найменший запас автономності: ~{Math.round(d.minTtc)} хв</span>
                  : d.minTtc != null && d.minTtc < 180
                    ? <span className="text-tertiary">⏱ Найменший запас: ~{Math.round(d.minTtc / 60 * 10) / 10} год</span>
                    : d.powerOnCount < d.total
                      ? <span className="text-on-surface-variant">⚡ {d.total - d.powerOnCount}/{d.total} без зовнішнього живлення</span>
                      : <span className="text-secondary">✓ Живлення стабільне, ризиків немає</span>;
              return (
                <div key={d.district} className="flex flex-col md:flex-row md:items-center gap-4">
                  <div className="md:w-1/4">
                    <span className="font-mono text-on-surface">{d.district}</span>
                    <p className="text-xs text-on-surface-variant mt-1">
                      {forecastLabel}
                    </p>
                  </div>
                  <div className="flex-1 h-8 bg-surface-bright/20 rounded relative overflow-hidden flex">
                    <div className={`h-full ${barColor} transition-all`} style={{ width: `${Math.max(0, d.avg)}%` }} />
                  </div>
                  <span className={`font-mono text-sm ${textColor}`}>{d.avg}</span>
                </div>
              );
            })}
          </div>
          <div className="mt-6 flex gap-4 text-xs font-mono justify-end">
            <div className="flex items-center gap-1 text-secondary"><i className="material-symbols-outlined text-[14px]">check_circle</i> Стабільно (&gt;70)</div>
            <div className="flex items-center gap-1 text-tertiary"><i className="material-symbols-outlined text-[14px]">warning</i> Увага (40-70)</div>
            <div className="flex items-center gap-1 text-error"><i className="material-symbols-outlined text-[14px]">error</i> Критично (&lt;40)</div>
          </div>
        </div>

        {/* Event Timeline */}
        <div className="glass-card rounded-xl p-[24px]">
          <div className="flex items-center gap-3 mb-6 border-b border-outline-variant/20 pb-4">
            <i className="material-symbols-outlined text-on-surface-variant">history</i>
            <h3 className="text-[20px] font-semibold text-on-surface">Хронологія подій</h3>
          </div>
          <div className="flex flex-col gap-2">
            {history.length === 0 && (
              <p className="text-[14px] text-on-surface-variant italic">Подій ще немає</p>
            )}
            {history.slice(0, 10).map((e, idx) => {
              const style = severityStyle[e.severity] ?? severityStyle.INFO;
              const isLast = idx === Math.min(history.length, 10) - 1;
              const timeStr = new Date(e.ts).toLocaleTimeString("uk-UA", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
              return (
                <div key={e.id} className="flex gap-4 p-3 hover:bg-surface-bright/5 rounded-lg transition-colors border border-transparent hover:border-outline-variant/10">
                  <div className="flex flex-col items-center mt-1">
                    <div className={`w-3 h-3 rounded-full ${style.dotClass}`} />
                    {!isLast && <div className="w-px flex-1 bg-outline-variant/20 my-2" />}
                  </div>
                  <div className="flex flex-col gap-1 w-full">
                    <div className="flex justify-between items-start">
                      <div className="flex items-center gap-2">
                        <i className={`material-symbols-outlined text-[16px] ${style.textClass}`}>{style.icon}</i>
                        <span className={`text-[14px] font-medium ${style.textClass}`}>{e.message}</span>
                      </div>
                      <span className="font-mono text-[12px] text-on-surface-variant whitespace-nowrap">
                        {timeStr}
                      </span>
                    </div>
                    <div className="text-[11px] text-on-surface-variant/60 ml-6">
                      {relativeTime(e.ts)}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </main>

      <MobileNav />
    </div>
  );
}

function KpiCard({ title, icon, iconColor, value, trend, trendValue }: { title: string; icon: string; iconColor: string; value: string; trend: "up" | "down" | "stable"; trendValue: string }) {
  const trendColor = trend === "up" ? "text-secondary bg-secondary/10" : trend === "down" ? "text-error bg-error/10" : "text-on-surface-variant bg-surface-bright/20";
  return (
    <div className="glass-card rounded-xl p-[24px] relative overflow-hidden group hover:border-primary/50 transition-colors">
      <div className="absolute top-0 right-0 w-32 h-32 bg-primary/5 rounded-full blur-2xl -mr-10 -mt-10" />
      <div className="flex justify-between items-start mb-4">
        <h3 className="font-bold text-[12px] uppercase tracking-wider text-on-surface-variant">{title}</h3>
        <i className={`material-symbols-outlined ${iconColor}`}>{icon}</i>
      </div>
      <div className="flex items-end gap-4">
        <span className="font-mono text-[40px] leading-none text-on-surface font-bold">{value}</span>
        <div className={`flex items-center ${trendColor} px-2 py-1 rounded text-xs font-mono`}>
          <i className="material-symbols-outlined text-[14px]">{trend === "up" ? "trending_up" : trend === "down" ? "trending_down" : "horizontal_rule"}</i>
          {trendValue}
        </div>
      </div>
    </div>
  );
}

function ProgressBar({ label, value, color, glow, suffix }: { label: string; value: number; color: string; glow?: string; suffix?: string }) {
  const colorClass = color === "secondary" ? "bg-secondary" : color === "primary" ? "bg-primary" : color === "tertiary" ? "bg-tertiary" : "bg-error";
  const textClass = color === "secondary" ? "text-secondary" : color === "primary" ? "text-primary" : color === "tertiary" ? "text-tertiary" : "text-error";
  return (
    <div>
      <div className="flex justify-between font-mono text-sm mb-1">
        <span className="text-on-surface-variant">{label}{suffix && <span className="text-on-surface-variant/70 text-[11px] ml-1">{suffix}</span>}</span>
        <span className={textClass}>{value}%</span>
      </div>
      <div className="w-full bg-surface-bright/30 rounded-full h-2 overflow-hidden">
        <div className={`h-2 rounded-full ${colorClass} ${glow ?? ""}`} style={{ width: `${value}%` }} />
      </div>
    </div>
  );
}

interface HistoricalData { t: Date; value: number }

function linePath(values: number[]): string {
  if (values.length === 0) return "";
  const max = 100;
  const min = 0;
  const step = 100 / (values.length - 1);
  return values
    .map((v, i) => {
      const x = i * step;
      const y = 100 - ((v - min) / (max - min)) * 100;
      return `${i === 0 ? "M" : "L"}${x},${y}`;
    })
    .join(" ");
}
function fillPath(values: number[]): string {
  if (values.length === 0) return "";
  return `${linePath(values)} L100,100 L0,100 Z`;
}