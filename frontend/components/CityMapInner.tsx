"use client";

import { MapContainer, TileLayer, Marker, Popup, Circle } from "react-leaflet";
import L from "leaflet";
import { useEffect, useMemo, useRef } from "react";
import type { ObjectState, StatusT } from "@/lib/types";
import { OBJECT_TYPE_UA, STATUS_LABEL_UA } from "@/lib/types";
import { buildOperatorBrief, type OperatorBrief } from "@/lib/recommendations";

const statusColor: Record<StatusT, string> = {
  STABLE: "#4ae176",
  WARNING: "#df7412",
  CRITICAL: "#ffb4ab",
  RESCUE_IN_TRANSIT: "#9b59b6",
};

// Гліф ресурсу, який потрібно доставити — для миттєвого сприйняття оператором.
const RESOURCE_GLYPH: Record<string, string> = {
  GENERATOR: "🔌",
  STARLINK: "📡",
  TECH_TEAM: "🔧",
  FUEL: "⛽",
  BATTERY_BANK: "🔋",
  EVACUATION: "🚨",
};

const NEED_LABEL: Record<string, string> = {
  GENERATOR: "Генератор",
  STARLINK: "Starlink",
  TECH_TEAM: "Техбригада",
  FUEL: "Паливо",
  BATTERY_BANK: "Резервна батарея",
  EVACUATION: "Евакуація",
};

function needGlyph(brief: OperatorBrief): string | null {
  if (brief.urgency === "ok" || brief.urgency === "watch") return null;
  if (!brief.suggestedResource) return null;
  return RESOURCE_GLYPH[brief.suggestedResource] ?? "⚠";
}

function makeIcon(status: StatusT, need: string | null): L.DivIcon {
  const color = statusColor[status];
  const pulseRing = status === "CRITICAL"
    ? `<div style="
        position:absolute; top:-6px; left:-6px;
        width:34px; height:34px; border-radius:50%;
        border:2px solid ${color};
        animation: pulse-ring 1.5s cubic-bezier(0.4,0,0.6,1) infinite;
        opacity:0.6;
      "></div>`
    : "";
  // Бейдж-потреба: що саме треба доставити на об'єкт.
  const needBadge = need
    ? `<div style="
        position:absolute; top:-12px; right:-12px;
        width:20px; height:20px; border-radius:50%;
        background: #0B1220; border: 1.5px solid #df7412;
        font-size: 11px;
        display:flex; align-items:center; justify-content:center;
        box-shadow: 0 0 8px #df7412aa;
      ">${need}</div>`
    : "";
  return L.divIcon({
    className: "resq-marker",
    html: `
      <div style="position:relative; width:22px; height:22px;">
        ${pulseRing}
        ${needBadge}
        <div style="
          width: 22px; height: 22px; border-radius: 50%;
          background: ${color}; border: 2px solid #0B1220;
          box-shadow: 0 0 0 3px ${color}66, 0 0 12px ${color};
          position:relative;
        ">
          <div style="
            position:absolute; top:50%; left:50%; transform:translate(-50%,-50%);
            width:8px; height:8px; border-radius:50%;
            background: white; opacity:0.7;
            box-shadow: 0 0 4px white;
          "></div>
        </div>
      </div>
    `,
    iconSize: [22, 22],
    iconAnchor: [11, 11],
  });
}

function makeVehicleIcon(label: string, kind: "outbound" | "inbound"): L.DivIcon {
  const color = kind === "outbound" ? "#9b59b6" : "#4ae176";
  return L.divIcon({
    className: "resq-vehicle",
    html: `
      <div style="position:relative; width:36px; height:36px; display:flex; align-items:center; justify-content:center;">
        <div style="
          position:absolute; inset:0; border-radius:50%;
          background: ${color}22; border: 2px solid ${color};
          animation: pulse-ring 1.2s ease-in-out infinite;
        "></div>
        <div style="
          width:28px; height:28px; border-radius:50%;
          background: ${color}; border: 2px solid #0B1220;
          display:flex; align-items:center; justify-content:center;
          font-size:14px; color:white; font-weight:700;
          box-shadow: 0 0 12px ${color};
        ">${kind === "outbound" ? "🚚" : "↩"}</div>
        <div style="
          position:absolute; top:-4px; right:-4px;
          background: #0B1220; color: ${color};
          font-size: 9px; font-weight: 700;
          padding: 1px 4px; border-radius: 4px;
          border: 1px solid ${color};
          white-space: nowrap;
        ">${label}</div>
      </div>
    `,
    iconSize: [36, 36],
    iconAnchor: [18, 18],
  });
}

const ZHYTOMYR_CENTER: [number, number] = [50.2647, 28.6647];
const DEPOT_LOCATION: [number, number] = [50.255, 28.65];
const CARTO_DARK = "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png";
const CARTO_ATTR =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="carto.com/attributions">CARTO</a>';

export interface RescueVehicle {
  id: string;
  from: [number, number];
  waypoint?: [number, number];
  to: [number, number];
  startMs: number;
  endMs: number;
  label: string;
  phase?: "outbound" | "inbound";
  onComplete?: () => void;
}

function lerp(a: number, b: number, t: number) {
  return a + (b - a) * t;
}

/** Квадратичний Безьє для руху через waypoint. */
function quadBezier(
  p0: [number, number],
  p1: [number, number],
  p2: [number, number],
  t: number
): [number, number] {
  const u = 1 - t;
  return [
    u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
    u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1],
  ];
}

function VehicleMarker({ vehicle }: { vehicle: RescueVehicle }) {
  const markerRef = useRef<L.Marker | null>(null);
  const rafRef = useRef<number | null>(null);
  const startRef = useRef<number>(performance.now());
  const completedRef = useRef(false);

  useEffect(() => {
    startRef.current = performance.now();
    completedRef.current = false;

    const tick = (now: number) => {
      const elapsed = now - startRef.current;
      const duration = vehicle.endMs - vehicle.startMs;
      const t = Math.max(0, Math.min(1, elapsed / duration));
      // ease-in-out
      const ease = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
      let pos: [number, number];
      if (vehicle.waypoint) {
        // Квадратичний Безьє: from → waypoint → to
        pos = quadBezier(vehicle.from, vehicle.waypoint, vehicle.to, ease);
      } else {
        pos = [lerp(vehicle.from[0], vehicle.to[0], ease), lerp(vehicle.from[1], vehicle.to[1], ease)];
      }
      if (markerRef.current) {
        markerRef.current.setLatLng(pos);
      }
      if (t >= 1) {
        if (!completedRef.current) {
          completedRef.current = true;
          vehicle.onComplete?.();
        }
        return;
      }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [vehicle]);

  const initialPos: [number, number] = [
    vehicle.from[0],
    vehicle.from[1],
  ];
  return (
    <Marker
      ref={(m) => {
        markerRef.current = m;
      }}
      position={initialPos}
      icon={makeVehicleIcon(vehicle.label, vehicle.phase ?? "outbound")}
      zIndexOffset={1000}
    />
  );
}

export default function CityMapInner({
  objects,
  selectedId,
  onSelect,
  className,
  rescueVehicles = [],
}: {
  objects: ObjectState[];
  selectedId?: string | null;
  onSelect?: (id: string) => void;
  className?: string;
  rescueVehicles?: RescueVehicle[];
}) {
  const markers = useMemo(
    () =>
      objects.map((o) => {
        const status = (o.score?.status ?? "STABLE") as StatusT;
        const brief = buildOperatorBrief(o, o.score, o.telemetry);
        const need = needGlyph(brief);
        return { obj: o, status, brief, need, icon: makeIcon(status, need) };
      }),
    [objects],
  );

  return (
    <MapContainer
      center={ZHYTOMYR_CENTER}
      zoom={12}
      className={className}
      scrollWheelZoom
      style={{ background: "#0B1220" }}
    >
      <TileLayer url={CARTO_DARK} attribution={CARTO_ATTR} />
      {/* Депo (база техніки) */}
      <Marker
        position={DEPOT_LOCATION}
        icon={L.divIcon({
          className: "resq-depot",
          html: `<div style="width:18px; height:18px; border-radius:4px; background:#4ae176; border:2px solid #0B1220; display:flex; align-items:center; justify-content:center; font-size:11px; color:white; box-shadow:0 0 10px #4ae176;">🏠</div>`,
          iconSize: [18, 18],
          iconAnchor: [9, 9],
        })}
      >
        <Popup>
          <div className="text-xs">
            <div className="font-semibold mb-1">База техніки</div>
            <div>Звідси виїжджає допомога</div>
          </div>
        </Popup>
      </Marker>
      {markers.map(({ obj, status, brief, need, icon }) => (
        <Marker
          key={obj.id}
          position={[obj.lat, obj.lon]}
          icon={icon}
          eventHandlers={{ click: () => onSelect?.(obj.id) }}
        >
          <Popup>
            <div className="text-sm min-w-[180px]">
              <div className="font-semibold text-base mb-2 border-b border-white/10 pb-2">
                {obj.name}
              </div>
              <div className="text-xs opacity-70 mb-1">{OBJECT_TYPE_UA[obj.type]} · {obj.district}</div>
              <div className="flex items-center gap-1 mb-1">
                <span style={{color: statusColor[status]}} className="font-bold">{STATUS_LABEL_UA[status]}</span>
              </div>
              {obj.score && <div className="font-mono text-xs">Score: <b>{Math.round(obj.score.score)}</b>/100</div>}
              {obj.telemetry && (
                <div className="grid grid-cols-2 gap-1 mt-2 text-xs font-mono">
                  <span>🔋 {Math.round(obj.telemetry.battery_pct)}%</span>
                  <span>🌡️ {obj.telemetry.temp_c?.toFixed(1)}°C</span>
                  <span>👥 {obj.telemetry.occupancy}/{obj.capacity}</span>
                  <span>
                    {obj.telemetry.power_on
                      ? '⚡ Мережа'
                      : obj.telemetry.generator_on
                        ? '🔌 Генератор'
                        : '❌ Без живлення'}
                  </span>
                </div>
              )}
              {need && brief.suggestedResource && status !== "RESCUE_IN_TRANSIT" && (
                <div
                  style={{
                    marginTop: 8,
                    padding: "4px 6px",
                    borderRadius: 6,
                    background: "#df741222",
                    border: "1px solid #df741255",
                    color: "#df7412",
                    fontSize: 12,
                    fontWeight: 700,
                  }}
                >
                  {need} Потрібно: {NEED_LABEL[brief.suggestedResource] ?? brief.suggestedResource}
                </div>
              )}
            </div>
          </Popup>
        </Marker>
      ))}
      {rescueVehicles.map((v) => (
        <VehicleMarker key={v.id} vehicle={v} />
      ))}
      {selectedId &&
        markers
          .filter((m) => m.obj.id === selectedId)
          .map((m) => (
            <Circle
              key={`circle-${m.obj.id}`}
              center={[m.obj.lat, m.obj.lon]}
              radius={500}
              pathOptions={{
                color: statusColor[m.status],
                fillColor: statusColor[m.status],
                fillOpacity: 0.08,
                weight: 1,
              }}
            />
          ))}
    </MapContainer>
  );
}
