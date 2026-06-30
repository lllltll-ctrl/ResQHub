"use client";

import { useEffect } from "react";
import { MapContainer, TileLayer, Marker, Popup, Polyline } from "react-leaflet";
import L from "leaflet";
import type { PublicObject, StatusT } from "@/lib/types";

const statusColor: Record<string, string> = {
  STABLE: "#4ae176",
  WARNING: "#df7412",
  CRITICAL: "#ffb4ab",
  RESCUE_IN_TRANSIT: "#9b59b6",
};

function makeIcon(status: StatusT, selected: boolean): L.DivIcon {
  const color = statusColor[status] || statusColor.STABLE;
  const size = selected ? 30 : 22;
  const anchor = selected ? 15 : 11;
  const pulseRing = status === "STABLE" || selected
    ? `<div style="
        position:absolute; top:-8px; left:-8px;
        width:${size + 16}px; height:${size + 16}px; border-radius:50%;
        border:2px solid ${color};
        animation: pulse-ring 2s cubic-bezier(0.4,0,0.6,1) infinite;
        opacity:0.4;
      "></div>`
    : "";
  return L.divIcon({
    className: "resq-marker",
    html: `
      <div style="position:relative; width:${size}px; height:${size}px;">
        ${pulseRing}
        <div style="
          width: ${size}px; height: ${size}px; border-radius: 50%;
          background: ${color}; border: ${selected ? 3 : 2}px solid ${selected ? "#fff" : "#0B1220"};
          box-shadow: 0 0 0 ${selected ? 4 : 3}px ${color}66, 0 0 ${selected ? 18 : 12}px ${color};
          position:relative;
        ">
          <div style="
            position:absolute; top:50%; left:50%; transform:translate(-50%,-50%);
            width:${selected ? 10 : 8}px; height:${selected ? 10 : 8}px; border-radius:50%;
            background: white; opacity:0.7;
            box-shadow: 0 0 4px white;
          "></div>
        </div>
      </div>
    `,
    iconSize: [size, size],
    iconAnchor: [anchor, anchor],
  });
}

function makeUserIcon(): L.DivIcon {
  const color = "#4d8eff"; // primary blue
  return L.divIcon({
    className: "user-marker",
    html: `
      <div style="position:relative; width:20px; height:20px;">
        <div style="
          position:absolute; top:-8px; left:-8px;
          width:36px; height:36px; border-radius:50%;
          border:2px solid ${color};
          animation: pulse-ring 1.5s cubic-bezier(0.4,0,0.6,1) infinite;
          opacity:0.6;
        "></div>
        <div style="
          width: 20px; height: 20px; border-radius: 50%;
          background: ${color}; border: 2px solid #fff;
          box-shadow: 0 0 10px ${color};
        "></div>
      </div>
      <style>
        @keyframes pulse-ring {
          0% { transform: scale(0.5); opacity: 0.8; }
          100% { transform: scale(1.5); opacity: 0; }
        }
      </style>
    `,
    iconSize: [20, 20],
    iconAnchor: [10, 10],
  });
}

const CARTO_DARK = "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png";
const CARTO_ATTR = '&copy; <a href="https://carto.com/">CARTO</a>';

export default function ResidentMapInner({
  objects,
  userLat,
  userLon,
  selectedId,
  onSelect,
  className,
}: {
  objects: PublicObject[];
  userLat: number;
  userLon: number;
  selectedId?: string | null;
  onSelect?: (id: string) => void;
  className?: string;
}) {
  const selected = objects.find((o) => o.id === selectedId) ?? (objects.length > 0 ? objects[0] : null);

  return (
    <MapContainer
      center={[userLat, userLon]}
      zoom={13}
      className={className}
      scrollWheelZoom
      style={{ background: "#0B1220" }}
    >
      <TileLayer url={CARTO_DARK} attribution={CARTO_ATTR} />

      {/* User location marker */}
      <Marker position={[userLat, userLon]} icon={makeUserIcon()}>
        <Popup>
          <div className="font-bold">Моя локація</div>
        </Popup>
      </Marker>

      {/* Path to selected */}
      {selected && (
        <Polyline
          positions={[
            [userLat, userLon],
            [selected.lat, selected.lon],
          ]}
          pathOptions={{ color: "#4d8eff", weight: 3, dashArray: "5, 10", opacity: 0.7 }}
        />
      )}

      {/* Object markers */}
      {objects.map((obj) => (
        <Marker
          key={obj.id}
          position={[obj.lat, obj.lon]}
          icon={makeIcon(obj.status, obj.id === selectedId)}
          eventHandlers={{
            click: () => onSelect?.(obj.id),
          }}
        >
          <Popup>
            <div className="text-sm min-w-[180px]">
              <div className="font-semibold text-base mb-1 border-b border-white/10 pb-1">{obj.name}</div>
              <div className="text-xs opacity-70 mb-2">{obj.address}</div>
              <div className="flex items-center gap-2 mb-2 text-xs">
                <i className="material-symbols-outlined text-[14px]">directions_walk</i>
                {Math.round((obj.distance_m ?? 0) / 80)} хв пішки
              </div>
              <div className="grid grid-cols-2 gap-1 mt-2 text-xs font-mono">
                <span>{obj.power_on ? '⚡ Увімк.' : '❌ Вимк.'}</span>
                <span>📡 {obj.internet_on ? 'Увімк.' : 'Вимк.'}</span>
                <span className="col-span-2 mt-1">👥 {obj.occupancy}/{obj.capacity} місць</span>
              </div>
            </div>
          </Popup>
        </Marker>
      ))}
    </MapContainer>
  );
}
