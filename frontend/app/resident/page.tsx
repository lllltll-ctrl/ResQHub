"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { PublicObject, StatusT } from "@/lib/types";
import Link from "next/link";
import { ResidentMap } from "@/components/ResidentMap";
import { StatusPill } from "@/components/ui/StatusPill";

// Сторінка мешканця самодостатня: тягне лише /api/public/objects.
// Раніше була обгорнута в RealtimeProvider, який на кожному вході робив
// 6 зайвих запитів (dashboard, dashboardFull, routing, events…) і відкривав
// WebSocket — саме це гальмувало завантаження. Публічному екрану це не треба.
export default function ResidentPage() {
  return <ResidentShell />;
}

function ResidentShell() {
  const [position, setPosition] = useState<{ lat: number; lon: number }>({ lat: 50.2647, lon: 28.6647 });
  const [geoGranted, setGeoGranted] = useState(false);
  const [objects, setObjects] = useState<PublicObject[]>([]);
  const [filter, setFilter] = useState<"all" | "light" | "internet" | "SHELTER" | "RESILIENCE_POINT">("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [infoModal, setInfoModal] = useState<null | "privacy" | "support" | "protocol">(null);
  const [menuOpen, setMenuOpen] = useState<"notif" | "profile" | null>(null);

  useEffect(() => {
    // Try to get geolocation
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          setPosition({ lat: pos.coords.latitude, lon: pos.coords.longitude });
          setGeoGranted(true);
        },
        () => {
          setGeoGranted(false);
        }
      );
    }
  }, []);

  useEffect(() => {
    async function load() {
      try {
        const data = await api.publicObjects(position.lat, position.lon, 5000);
        setObjects(data);
      } catch (e) {
        console.error(e);
      } finally {
        setLoading(false);
      }
    }
    load();
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  }, [position]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setInfoModal(null);
        setMenuOpen(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const filtered = objects.filter((o) => {
    if (filter === "light") return o.power_on;
    if (filter === "internet") return o.internet_on;
    if (filter === "SHELTER") return o.type === "SHELTER";
    if (filter === "RESILIENCE_POINT") return o.type === "RESILIENCE_POINT";
    return true;
  });

  const nearest = filtered[0];
  const selectedObject = filtered.find((o) => o.id === selectedId) ?? nearest;

  function openRoute(lat: number, lon: number) {
    const url = `https://www.google.com/maps/dir/?api=1&origin=${position.lat},${position.lon}&destination=${lat},${lon}&travelmode=walking`;
    window.open(url, "_blank", "noopener,noreferrer");
  }

  return (
    <div className="flex flex-col min-h-screen bg-grid animate-fade-in-up">
      {/* Top nav */}
      <nav className="fixed top-0 w-full z-50 bg-surface/80 backdrop-blur-xl border-b border-white/10 shadow-sm flex justify-between items-center h-16 px-[32px]">
        <div className="flex items-center gap-6">
          <span className="text-[20px] font-bold text-primary tracking-tight font-[DM_Sans]">ResQHub</span>
          <div className="hidden md:flex gap-4 items-center">
            <Link href="/operations" className="text-on-surface-variant font-medium hover:text-on-surface transition-colors">Операційна</Link>
            <Link href="/analytics" className="text-on-surface-variant font-medium hover:text-on-surface transition-colors">Аналітика</Link>
            <span className="text-primary border-b-2 border-primary font-bold pb-1">Жителю</span>
          </div>
        </div>
        <div className="flex items-center gap-4 relative">
          <button
            onClick={() => setMenuOpen(menuOpen === "notif" ? null : "notif")}
            className="hover:bg-surface-container-high/50 rounded-lg transition-all p-2 active:scale-95 relative"
            aria-label="Сповіщення"
          >
            <i className="material-symbols-outlined text-primary">notifications</i>
            <span className="absolute top-1 right-1 w-2 h-2 bg-error rounded-full" />
          </button>
          {menuOpen === "notif" && (
            <div className="absolute right-12 top-12 w-80 glass-card rounded-lg p-4 z-50 shadow-xl border border-outline-variant/30">
              <div className="flex items-center justify-between mb-3">
                <h3 className="font-bold text-sm">Сповіщення</h3>
                <button onClick={() => setMenuOpen(null)} className="text-on-surface-variant hover:text-on-surface">
                  <i className="material-symbols-outlined text-[16px]">close</i>
                </button>
              </div>
              <div className="space-y-2 text-xs">
                <div className="p-2 rounded bg-error/10 border border-error/20">
                  <div className="font-medium text-error">Блекаут активний</div>
                  <div className="text-on-surface-variant mt-1">
                    Міськими службами зафіксовано масштабне відключення. Перевірте найближчі пункти.
                  </div>
                </div>
                <div className="p-2 rounded bg-tertiary/10 border border-tertiary/20">
                  <div className="font-medium text-tertiary">Пункт незламності поруч</div>
                  <div className="text-on-surface-variant mt-1">
                    У радіусі 500 м є 3 пункти зі стабільним живленням.
                  </div>
                </div>
              </div>
            </div>
          )}
          <button
            onClick={() => setMenuOpen(menuOpen === "profile" ? null : "profile")}
            className="hover:bg-surface-container-high/50 rounded-lg transition-all p-2 active:scale-95"
            aria-label="Профіль"
          >
            <i className="material-symbols-outlined text-primary">account_circle</i>
          </button>
          {menuOpen === "profile" && (
            <div className="absolute right-0 top-12 w-64 glass-card rounded-lg p-4 z-50 shadow-xl border border-outline-variant/30">
              <div className="flex items-center gap-3 mb-3 pb-3 border-b border-outline-variant/20">
                <div className="w-10 h-10 rounded-full bg-primary/20 flex items-center justify-center">
                  <i className="material-symbols-outlined text-primary">person</i>
                </div>
                <div>
                  <div className="font-medium text-sm">Гість</div>
                  <div className="text-xs text-on-surface-variant">Анонімний режим</div>
                </div>
              </div>
              <div className="space-y-1 text-xs">
                <button className="w-full text-left p-2 rounded hover:bg-surface-bright/20 transition-colors flex items-center gap-2">
                  <i className="material-symbols-outlined text-[16px]">language</i>
                  Мова інтерфейсу: Українська
                </button>
                <button className="w-full text-left p-2 rounded hover:bg-surface-bright/20 transition-colors flex items-center gap-2">
                  <i className="material-symbols-outlined text-[16px]">accessibility</i>
                  Версія для слабозорих
                </button>
                <button className="w-full text-left p-2 rounded hover:bg-error/10 text-error transition-colors flex items-center gap-2">
                  <i className="material-symbols-outlined text-[16px]">logout</i>
                  Вийти з режиму
                </button>
              </div>
            </div>
          )}
        </div>
      </nav>

      <main className="flex-1 pt-24 pb-8 px-4 md:px-[32px] flex flex-col gap-3">
        {/* Header */}
        <header className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
          <div>
            <h1 className="text-[32px] md:text-[48px] font-bold text-on-surface tracking-tight font-[DM_Sans] leading-tight">
              Центр Стійкості Міста: Житомир
            </h1>
            <p className="text-[16px] text-on-surface-variant mt-2 max-w-2xl">
              Оперативна інформація про доступність критичної інфраструктури та пунктів допомоги.
            </p>
          </div>
          {geoGranted && (
            <div className="flex items-center gap-2 bg-secondary/10 text-secondary px-3 py-1.5 rounded-lg border border-secondary/20">
              <i className="material-symbols-outlined text-[18px]">my_location</i>
              <span className="text-sm font-bold uppercase tracking-wider">Моя локація активна</span>
            </div>
          )}
        </header>

        {/* Dashboard grid */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 mt-4">
          {/* Map area (left) */}
          <div className="lg:col-span-8 flex flex-col gap-3">
            {/* Filters */}
            <div className="flex flex-wrap gap-3">
              <FilterBtn active={filter === "all"} onClick={() => setFilter("all")} icon="filter_list" label="Всі" />
              <FilterBtn active={filter === "light"} onClick={() => setFilter("light")} icon="bolt" label="Світло" highlight />
              <FilterBtn active={filter === "internet"} onClick={() => setFilter("internet")} icon="wifi" label="Зв'язок" highlight />
              <FilterBtn active={filter === "SHELTER"} onClick={() => setFilter("SHELTER")} icon="shield" label="Укриття" />
              <FilterBtn active={filter === "RESILIENCE_POINT"} onClick={() => setFilter("RESILIENCE_POINT")} icon="cell_tower" label="П. Незламності" />
            </div>

            {/* Real Map */}
            <div className="relative rounded-xl border border-white/5 overflow-hidden bg-[#111827] backdrop-blur min-h-[400px] lg:min-h-[500px] shadow-lg">
              <ResidentMap
                objects={filtered}
                userLat={position.lat}
                userLon={position.lon}
                selectedId={selectedId ?? undefined}
                onSelect={setSelectedId}
                className="absolute inset-0 w-full h-full"
              />

              {/* Overlay legend */}
              <div className="absolute bottom-3 left-3 glass-card rounded-lg p-2 flex gap-3 text-xs z-[1000] shadow-md border border-white/10 backdrop-blur-md">
                <span className="flex items-center gap-1 text-secondary">
                  <span className="w-2 h-2 bg-secondary rounded-full"></span>
                  Стабільний
                </span>
                <span className="flex items-center gap-1 text-tertiary">
                  <span className="w-2 h-2 bg-tertiary rounded-full"></span>
                  Увага
                </span>
                <span className="flex items-center gap-1 text-error">
                  <span className="w-2 h-2 bg-error rounded-full"></span>
                  Критичний
                </span>
              </div>
            </div>
          </div>

          {/* Right panel */}
          <div className="lg:col-span-4 flex flex-col gap-4">
            {/* Selected / nearest point card */}
            {selectedObject && (
              <div className="glass-panel rounded-xl p-6 glow-blue border border-primary/20 shadow-lg relative overflow-hidden group">
                <div className="absolute top-0 right-0 w-32 h-32 bg-primary/10 rounded-full blur-2xl -mr-10 -mt-10 transition-all group-hover:bg-primary/20" />
                <div className="flex items-start justify-between mb-4 relative z-10">
                  <div>
                    <h3 className="font-bold text-[12px] uppercase tracking-wider text-on-surface-variant mb-1 flex items-center gap-1">
                      <i className="material-symbols-outlined text-[14px] text-primary">location_on</i>
                      {selectedObject.id === nearest?.id ? "Найближчий пункт до вас" : "Обраний пункт"}
                    </h3>
                    <div className="text-[20px] font-semibold text-on-surface font-[DM_Sans]">
                      {selectedObject.name}
                    </div>
                    <div className="text-sm text-outline mt-1 flex items-center gap-1 text-on-surface-variant">
                      <i className="material-symbols-outlined text-[16px]">directions_walk</i>
                      {Math.round((selectedObject.distance_m ?? 0) / 80)} хв пішки · {selectedObject.distance_m} м
                    </div>
                  </div>
                  <div className="bg-secondary/20 text-secondary px-3 py-1 rounded-full font-bold text-[12px] uppercase tracking-wider border border-secondary/30">
                    Є МІСЦЯ
                  </div>
                </div>

                <div className="space-y-3 mt-6 border-t border-white/5 pt-4 relative z-10">
                  <Feature icon="bolt" label="Світло" value={selectedObject.power_on ? "Увімк." : "Вимк."} color={selectedObject.power_on ? "secondary" : "error"} />
                  <Feature icon="wifi" label="Starlink" value={selectedObject.internet_on ? "Увімк." : "Вимк."} color={selectedObject.internet_on ? "secondary" : "error"} />
                  <Feature icon="people" label="Заповненість" value={`${selectedObject.occupancy}/${selectedObject.capacity}`} color={selectedObject.occupancy < selectedObject.capacity * 0.8 ? "secondary" : "tertiary"} />
                </div>

                <button
                  onClick={() => openRoute(selectedObject.lat, selectedObject.lon)}
                  className="w-full bg-primary text-on-primary font-semibold text-[16px] uppercase tracking-wider py-3 rounded-lg hover:bg-primary-container hover:text-on-primary-container transition-all active:scale-95 flex items-center justify-center gap-2 mt-6 shadow-[0_0_15px_rgba(77,142,255,0.4)] hover:shadow-[0_0_25px_rgba(77,142,255,0.6)] relative z-10"
                >
                  <i className="material-symbols-outlined" style={{ fontVariationSettings: "'FILL' 1" }}>directions</i>
                  Маршрут
                </button>
              </div>
            )}

            {/* All objects list */}
            <div className="glass-panel rounded-xl p-6 flex-1 shadow-lg border border-white/5">
              <h3 className="font-bold text-[12px] uppercase tracking-wider text-on-surface-variant mb-4">
                Доступні пункти
              </h3>
              <div className="space-y-3 max-h-[500px] overflow-y-auto pr-2">
                {filtered.map((o) => (
                  <div
                    key={o.id}
                    onClick={() => setSelectedId(o.id)}
                    className={`border rounded-lg p-3 hover:bg-surface-bright/10 transition-colors cursor-pointer group ${
                      o.id === selectedId
                        ? "bg-primary-container/10 border-primary"
                        : "bg-surface-dim/30 border-outline-variant/20"
                    }`}
                  >
                    <div className="flex justify-between items-start mb-1">
                      <div className={`font-medium text-sm transition-colors ${o.id === selectedId ? "text-primary" : "group-hover:text-primary"}`}>{o.name}</div>
                      <StatusPill status={o.status} />
                    </div>
                    <div className="text-xs text-on-surface-variant flex items-center justify-between">
                      <span className="truncate max-w-[180px]">{o.address}</span>
                      <span className="font-mono bg-surface-bright/20 px-1.5 py-0.5 rounded">{Math.round((o.distance_m ?? 0) / 80)} хв</span>
                    </div>
                  </div>
                ))}
                {filtered.length === 0 && (
                  <div className="text-sm text-on-surface-variant text-center py-12 flex flex-col items-center gap-2">
                    <i className="material-symbols-outlined text-[32px] opacity-50">search_off</i>
                    {loading ? "Завантаження..." : "Поруч немає доступних пунктів"}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="w-full mt-auto bg-surface-container-lowest border-t border-outline-variant/20 flex flex-col md:flex-row justify-between items-center p-[24px] gap-4">
        <div className="font-bold text-[12px] uppercase tracking-wider text-on-surface-variant">
          © 2026 Міське оперативне командування
        </div>
        <div className="flex gap-4">
          <button
            onClick={() => setInfoModal("privacy")}
            className="text-on-surface-variant hover:text-primary transition-colors text-sm"
          >
            Конфіденційність
          </button>
          <button
            onClick={() => setInfoModal("support")}
            className="text-on-surface-variant hover:text-primary transition-colors text-sm"
          >
            Підтримка
          </button>
          <button
            onClick={() => setInfoModal("protocol")}
            className="text-on-surface-variant hover:text-primary transition-colors text-sm border border-outline-variant/30 px-2 py-0.5 rounded"
          >
            Протокол НС
          </button>
        </div>
      </footer>

      {/* Info modal */}
      {infoModal && (
        <div
          className="fixed inset-0 z-[100] bg-black/60 backdrop-blur-sm flex items-center justify-center p-4"
          onClick={() => setInfoModal(null)}
        >
          <div
            className="glass-card rounded-xl p-6 max-w-lg w-full shadow-2xl border border-outline-variant/30"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex justify-between items-start mb-4">
              <h2 className="text-xl font-semibold text-on-surface">
                {infoModal === "privacy" && "Політика конфіденційності"}
                {infoModal === "support" && "Підтримка"}
                {infoModal === "protocol" && "Протокол дій у надзвичайних ситуаціях"}
              </h2>
              <button
                onClick={() => setInfoModal(null)}
                className="text-on-surface-variant hover:text-on-surface p-1"
                aria-label="Закрити"
              >
                <i className="material-symbols-outlined">close</i>
              </button>
            </div>
            <div className="text-sm text-on-surface-variant space-y-3">
              {infoModal === "privacy" && (
                <>
                  <p>ResQHub збирає лише технічні дані телеметрії об'єктів міської інфраструктури (рівень заряду, температура, CO₂, кількість людей). Персональні дані користувачів не збираються і не передаються третім сторонам.</p>
                  <p>Геолокація використовується виключно для підбору найближчого пункту допомоги і не зберігається на сервері.</p>
                </>
              )}
              {infoModal === "support" && (
                <>
                  <p><strong className="text-on-surface">Гаряча лінія міста:</strong> 15-80 (цілодобово)</p>
                  <p><strong className="text-on-surface">ДСНС Житомирщини:</strong> 101</p>
                  <p><strong className="text-on-surface">Екстрена медична допомога:</strong> 103</p>
                  <p><strong className="text-on-surface">Поліція:</strong> 102</p>
                  <p>Якщо ваш об'єкт відсутній у списку або показники не відповідають дійсності — повідомте оператора через гарячу лінію.</p>
                </>
              )}
              {infoModal === "protocol" && (
                <>
                  <p><strong className="text-on-surface">1. Зберігайте спокій.</strong> Паніка погіршує ситуацію.</p>
                  <p><strong className="text-on-surface">2. Перевірте найближчий пункт</strong> зі стабільним живленням та зв'язком на карті вище.</p>
                  <p><strong className="text-on-surface">3. Візьміть документи, медикаменти, зарядний пристрій, запас води.</strong></p>
                  <p><strong className="text-on-surface">4. Дотримуйтесь вказівок рятувальних служб</strong> та офіційних каналів інформації.</p>
                  <p><strong className="text-on-surface">5. Не наближайтесь до пошкоджених ліній електропередач.</strong></p>
                </>
              )}
            </div>
            <button
              onClick={() => setInfoModal(null)}
              className="w-full mt-6 bg-primary text-on-primary font-semibold py-2 rounded-lg hover:bg-primary-container transition-colors"
            >
              Зрозуміло
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function FilterBtn({
  active,
  onClick,
  icon,
  label,
  highlight,
}: {
  active: boolean;
  onClick: () => void;
  icon: string;
  label: string;
  highlight?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-2 px-4 py-2 rounded-full border transition-all font-bold text-[12px] uppercase tracking-wider shadow-sm active:scale-95 ${
        active && highlight
          ? "bg-primary-container text-on-primary-container border-primary/30 shadow-[0_0_10px_rgba(77,142,255,0.2)]"
          : active
            ? "bg-surface-container-highest text-on-surface border-white/10"
            : "bg-surface-container-low text-on-surface-variant border-white/5 hover:bg-surface-container-highest hover:text-on-surface"
      }`}
    >
      <i className={`material-symbols-outlined text-sm ${highlight ? "text-primary" : ""}`}>{icon}</i>
      {label}
    </button>
  );
}

function Feature({ icon, label, value, color }: { icon: string; label: string; value: string; color: string }) {
  const colorClass = color === "secondary" ? "text-secondary" : color === "error" ? "text-error" : "text-tertiary";
  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-2 text-on-surface-variant">
        <i className={`material-symbols-outlined ${colorClass}`}>{icon}</i>
        <span className="text-[14px] font-medium">{label}</span>
      </div>
      <span className={`font-mono text-[14px] font-bold ${colorClass}`}>{value}</span>
    </div>
  );
}
