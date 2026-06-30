"use client";

import dynamic from "next/dynamic";
import { SkeletonMap } from "@/components/LoadingSkeleton";

const ResidentMapInner = dynamic(() => import("./ResidentMapInner"), {
  ssr: false,
  loading: () => <SkeletonMap />,
});

export function ResidentMap(props: any) {
  return <ResidentMapInner {...props} />;
}
