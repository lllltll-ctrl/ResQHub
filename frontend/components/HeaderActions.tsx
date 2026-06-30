"use client";

import { useEffect, useState } from "react";

export function HeaderActions({ accent = "primary" }: { accent?: "primary" | "secondary" }) {
  const [open, setOpen] = useState<"notif" | "profile" | null>(null);
  const accentClass = accent === "primary" ? "text-primary" : "text-secondary";

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="flex items-center gap-2 relative">
      <button
        onClick={() => setOpen(open === "notif" ? null : "notif")}
        className="hover:bg-surface-container-high/50 rounded-lg transition-all p-2 active:scale-95 relative"
        aria-label="Сповіщення"
      >
        <i className={`material-symbols-outlined ${accentClass}`}>notifications</i>
        <span className="absolute top-1 right-1 w-2 h-2 bg-error rounded-full" />
      </button>
      {open === "notif" && (
        <div className="absolute right-12 top-12 w-80 glass-card rounded-lg p-4 z-[70] shadow-xl border border-outline-variant/30">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-bold text-sm">Сповіщення</h3>
            <button onClick={() => setOpen(null)} className="text-on-surface-variant hover:text-on-surface">
              <i className="material-symbols-outlined text-[16px]">close</i>
            </button>
          </div>
          <div className="space-y-2 text-xs">
            <div className="p-2 rounded bg-tertiary/10 border border-tertiary/20">
              <div className="font-medium text-tertiary">Система готова</div>
              <div className="text-on-surface-variant mt-1">
                Всі об'єкти моніторяться у реальному часі.
              </div>
            </div>
            <div className="p-2 rounded bg-surface-bright/10 border border-outline-variant/10">
              <div className="font-medium text-on-surface">Демо-режим</div>
              <div className="text-on-surface-variant mt-1">
                Спробуйте кнопку "Симулювати блекаут" на операційній панелі.
              </div>
            </div>
          </div>
        </div>
      )}
      <button
        onClick={() => setOpen(open === "profile" ? null : "profile")}
        className="hover:bg-surface-container-high/50 rounded-lg transition-all p-2 active:scale-95"
        aria-label="Профіль"
      >
        <i className={`material-symbols-outlined ${accentClass}`}>account_circle</i>
      </button>
      {open === "profile" && (
        <div className="absolute right-0 top-12 w-64 glass-card rounded-lg p-4 z-[70] shadow-xl border border-outline-variant/30">
          <div className="flex items-center gap-3 mb-3 pb-3 border-b border-outline-variant/20">
            <div className="w-10 h-10 rounded-full bg-primary/20 flex items-center justify-center">
              <i className="material-symbols-outlined text-primary">person</i>
            </div>
            <div>
              <div className="font-medium text-sm">Оператор штабу</div>
              <div className="text-xs text-on-surface-variant">Житомир / НС</div>
            </div>
          </div>
          <div className="space-y-1 text-xs">
            <button className="w-full text-left p-2 rounded hover:bg-surface-bright/20 transition-colors flex items-center gap-2">
              <i className="material-symbols-outlined text-[16px]">settings</i>
              Налаштування сповіщень
            </button>
            <button className="w-full text-left p-2 rounded hover:bg-surface-bright/20 transition-colors flex items-center gap-2">
              <i className="material-symbols-outlined text-[16px]">help</i>
              Документація API
            </button>
            <button className="w-full text-left p-2 rounded hover:bg-error/10 text-error transition-colors flex items-center gap-2">
              <i className="material-symbols-outlined text-[16px]">logout</i>
              Завершити сесію
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
