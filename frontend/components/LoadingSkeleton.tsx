"use client";

export function SkeletonCard({ className = "" }: { className?: string }) {
  return (
    <div className={`glass-card rounded-xl p-6 ${className}`}>
      <div className="skeleton h-3 w-24 mb-4" />
      <div className="skeleton h-8 w-16 mb-2" />
      <div className="skeleton h-2 w-full" />
    </div>
  );
}

export function SkeletonTable({ rows = 5 }: { rows?: number }) {
  return (
    <div className="flex flex-col gap-2">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex gap-4 py-3 px-4">
          <div className="skeleton h-4 w-32" />
          <div className="skeleton h-4 w-20" />
          <div className="skeleton h-4 w-16" />
          <div className="skeleton h-4 w-24" />
          <div className="skeleton h-4 w-12 ml-auto" />
        </div>
      ))}
    </div>
  );
}

export function SkeletonMap() {
  return (
    <div className="w-full h-full bg-[#0b0e15] flex items-center justify-center">
      <div className="flex flex-col items-center gap-3">
        <i className="material-symbols-outlined text-4xl text-on-surface-variant animate-pulse">map</i>
        <span className="text-sm text-on-surface-variant">Завантаження карти...</span>
      </div>
    </div>
  );
}

export function DashboardSkeleton() {
  return (
    <div className="flex flex-col h-screen overflow-hidden animate-fade-in-up">
      <div className="h-16 skeleton" />
      <div className="flex flex-1 pt-16">
        <aside className="w-[320px] p-6 flex flex-col gap-4 hidden md:flex">
          <SkeletonCard />
          <div className="grid grid-cols-3 gap-1">
            <SkeletonCard />
            <SkeletonCard />
            <SkeletonCard />
          </div>
          <SkeletonCard className="flex-1" />
        </aside>
        <main className="flex-1 flex flex-col">
          <div className="flex-1 skeleton" />
          <div className="h-[40%] p-4"><SkeletonTable /></div>
        </main>
      </div>
    </div>
  );
}
