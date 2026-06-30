"use client";

import dynamic from "next/dynamic";
import type { ObjectState } from "@/lib/types";

const CityMapInner = dynamic(() => import("./CityMapInner"), {
  ssr: false,
  loading: () => (
    <div className="absolute inset-0 flex items-center justify-center bg-[#0b0e15] text-on-surface-variant text-sm">
      Завантаження карти...
    </div>
  ),
});

export function CityMap(props: {
  objects: ObjectState[];
  selectedId?: string | null;
  onSelect?: (id: string) => void;
  className?: string;
}) {
  return <CityMapInner {...props} />;
}