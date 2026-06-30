"use client";

import { useEffect, useState } from "react";

export interface Toast {
  id: number;
  message: string;
  type: "success" | "error" | "info" | "warning";
}

let nextId = 1;
let listeners: Array<(t: Toast) => void> = [];

export function pushToast(message: string, type: Toast["type"] = "success") {
  const t: Toast = { id: nextId++, message, type };
  listeners.forEach((l) => l(t));
}

export function ToastContainer() {
  const [toasts, setToasts] = useState<Toast[]>([]);

  useEffect(() => {
    function handle(t: Toast) {
      setToasts((cur) => [...cur, t]);
      setTimeout(() => setToasts((cur) => cur.filter((x) => x.id !== t.id)), 3500);
    }
    listeners.push(handle);
    return () => {
      listeners = listeners.filter((l) => l !== handle);
    };
  }, []);

  return (
    <div className="fixed bottom-6 right-6 z-[9999] flex flex-col gap-2 pointer-events-none">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={`px-4 py-3 rounded-lg backdrop-blur-md shadow-lg text-sm font-medium animate-in ${
            t.type === "success"
              ? "bg-secondary/20 border border-secondary/40 text-secondary"
              : t.type === "error"
                ? "bg-error/20 border border-error/40 text-error"
                : t.type === "warning"
                  ? "bg-tertiary-container/20 border border-tertiary/40 text-tertiary"
                  : "bg-primary/20 border border-primary/40 text-primary"
          }`}
          style={{ animation: "slideIn 0.25s ease-out" }}
        >
          <div className="flex items-center gap-2">
            <i className="material-symbols-outlined text-[18px]">
              {t.type === "success" ? "check_circle" : t.type === "error" ? "error" : t.type === "warning" ? "warning" : "info"}
            </i>
            {t.message}
          </div>
        </div>
      ))}
      <style jsx>{`
        @keyframes slideIn {
          from { transform: translateX(20px); opacity: 0; }
          to { transform: translateX(0); opacity: 1; }
        }
      `}</style>
    </div>
  );
}