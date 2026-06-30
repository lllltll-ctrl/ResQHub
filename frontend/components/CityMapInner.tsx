"use client";

import { MapContainer, TileLayer, Marker, Popup, Circle } from "react-leaflet";
import L from "leaflet";
import { useMemo } from "react";
import type { ObjectState, StatusT } from "@/lib/types";
import { OBJECT_TYPE_UA, STATUS_LABEL_UA } from "@/lib/types";

const statusColor: Record<StatusT, string> = {
  STABLE: "#4ae176",
  WARNING: "#df7412",
  CRITICAL: "#ffb4ab",
  RESCUE_IN_TRANSIT: "#9b59b6",
};

function makeIcon(status: StatusT): L.DivIcon {
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
  return L.divIcon({
    className: "resq-marker",
    html: `
      <div style="position:relative; width:22px; height:22px;">
        ${pulseRing}
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

const ZHYTOMYR_CENTER: [number, number] = [50.2647, 28.6647];
const CARTO_DARK = "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png";
const CARTO_ATTR =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/attributions">CARTO</a>';

export default function CityMapInner({
  objects,
  selectedId,
  onSelect,
  className,
}: {
  objects: ObjectState[];
  selectedId?: string | null;
  onSelect?: (id: string) => void;
  className?: string;
}) {
  const markers = useMemo(
    () =>
      objects.map((o) => {
        const status = (o.score?.status ?? "STABLE") as StatusT;
        return { obj: o, status, icon: makeIcon(status) };
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
      {markers.map(({ obj, status, icon }) => (
        <Marker
          key={obj.id}
          position={[obj.lat, obj.lon]}
          icon={icon}
          eventHandlers={{ click: () => onSelect?.(obj.id) }}
        >
          <Popup>
            <div className="text-sm min-w-[180px]">
              <div className="font-semibold text-base mb-2 border-b border-white/10 pb-2">{obj.name}</div>
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
                  <span>{obj.telemetry.power_on ? '⚡ ON' : '❌ OFF'}</span>
                </div>
              )}
            </div>
          </Popup>
        </Marker>
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