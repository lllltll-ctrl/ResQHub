"use client";

import { useStore } from "@/lib/store";
import { RESOURCE_TYPE_UA, SCENARIO_TYPE_UA, SCENARIO_SCOPE_UA, STATUS_LABEL_UA } from "@/lib/types";

function translateEventMessage(message: string): string {
  let result = message;

  // Resource types
  Object.entries(RESOURCE_TYPE_UA).forEach(([en, ua]) => {
    result = result.replace(new RegExp(`\\b${en}\\b`, "g"), ua);
  });

  // Status values
  Object.entries(STATUS_LABEL_UA).forEach(([en, ua]) => {
    result = result.replace(new RegExp(`\\b${en}\\b`, "g"), ua);
  });

  // Scenario types
  Object.entries(SCENARIO_TYPE_UA).forEach(([en, ua]) => {
    result = result.replace(new RegExp(`\\b${en}\\b`, "g"), ua);
  });

  // Scenario scopes
  Object.entries(SCENARIO_SCOPE_UA).forEach(([en, ua]) => {
    result = result.replace(new RegExp(`\\b${en}\\b`, "g"), ua);
  });

  // Common labels
  result = result.replace(/\bscope=/g, "область=");
  result = result.replace(/\bintensity=/g, "інтенсивність=");
  result = result.replace(/\bscore\b/gi, "бал");
  result = result.replace(/\bETA\b/g, "прибуття через");
  result = result.replace(/\[OPTIMIZED:/g, "[ОПТИМІЗОВАНО:");

  // Remove quotes around object names
  result = result.replace(/'([^']+)'/g, "$1");

  return result;
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

export function EventLog() {
  // Оперативний журнал: лише події поточної сесії (приходять через WS
  // push у RealtimeProvider). На вході порожній — історія в Аналітиці.
  const { events, clearEvents } = useStore();

  function formatTime(ts: string): string {
    try {
      const d = new Date(ts);
      return d.toLocaleTimeString("uk-UA", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    } catch {
      return ts;
    }
  }

  const displayed = events.slice(0, 15);

  return (
    <div className="flex flex-col gap-3 mt-2">
      <div className="flex items-center gap-2 text-on-surface-variant mb-2">
        <i className="material-symbols-outlined text-[18px]">history</i>
        <h3 className="font-bold text-[12px] uppercase tracking-wider">Журнал дій</h3>
        {events.length > 0 && (
          <>
            <span className="ml-auto bg-primary-container/20 text-primary font-mono text-[11px] px-2 py-0.5 rounded-full border border-primary/20">
              {events.length}
            </span>
            <button
              onClick={() => clearEvents()}
              title="Очистити журнал"
              className="text-on-surface-variant/60 hover:text-error transition-colors p-1 rounded hover:bg-error/10"
            >
              <i className="material-symbols-outlined text-[14px]">delete_sweep</i>
            </button>
          </>
        )}
      </div>
      {events.length === 0 && (
        <p className="text-[14px] text-on-surface-variant italic">Подій ще немає</p>
      )}
      {displayed.map((e, idx) => {
        const style = severityStyle[e.severity] ?? severityStyle.INFO;
        const isLast = idx === displayed.length - 1;
        return (
          <div key={e.id} className="flex gap-3 hover:bg-surface-bright/5 rounded-lg px-2 transition-colors cursor-default">
            <div className="flex flex-col items-center mt-1">
              <div className={`w-2 h-2 rounded-full ${style.dotClass}`} />
              {!isLast && <div className="w-px flex-1 bg-outline-variant/20 my-1" />}
            </div>
            <div className="flex flex-col gap-1 pb-4">
              <div className="flex items-center gap-1.5">
                <i className={`material-symbols-outlined text-[14px] ${style.textClass}`}>{style.icon}</i>
                <p className={`text-[14px] ${style.textClass}`}>{translateEventMessage(e.message)}</p>
              </div>
              <div className="flex items-center gap-2">
                <span className="font-mono text-[12px] text-on-surface-variant">
                  {formatTime(e.ts)}
                </span>
                <span className="font-mono text-[11px] text-on-surface-variant/50">
                  · {relativeTime(e.ts)}
                </span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}