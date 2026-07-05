"use client";

import { useEffect, useRef } from "react";
import { useStore } from "@/lib/store";
import { api } from "@/lib/api";
import { wsUrl } from "@/lib/config";
import type {
  DashboardSummary,
  ObjectState,
  WsSnapshot,
  BoltEvent,
  Scenario,
  Assignment,
} from "@/lib/types";

export function RealtimeProvider({ children }: { children: React.ReactNode }) {
  const {
    setObjects,
    setSummary,
    setWsConnected,
    setRouting,
    setActiveScenario,
    setAssignments,
    appendEvent,
  } = useStore();
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let cancelled = false;
    let reconnectTimer: ReturnType<typeof setTimeout>;

    async function bootstrap() {
      try {
        // Події НЕ тягнемо у bootstrap: оперативний журнал стартує порожнім
        // і наповнюється лише новими подіями через WS (appendEvent).
        const [summary, objects, routing, scenario, assignments] = await Promise.all([
          api.dashboard(),
          api.dashboardFull(),
          api.routing(5),
          api.activeScenario(),
          api.assignments(),
        ]);
        if (cancelled) return;
        setSummary(summary as DashboardSummary);
        setObjects(objects as ObjectState[]);
        setRouting(routing);
        setActiveScenario(scenario as Scenario | null);
        setAssignments(assignments);
      } catch (e) {
        console.error("[bootstrap] failed:", e);
      }
    }

    // Час останнього повідомлення від сервера. Сервер шле snapshot кожні
    // ~3с, тож тиша довша за 20с = «зомбі»-з'єднання (ноутбук спав, мобільна
    // вкладка у фоні) — браузер НЕ кидає onclose у таких випадках, і без
    // watchdog сторінка назавжди застигала зі старими даними.
    let lastMessageAt = Date.now();

    function connectWs() {
      const ws = new WebSocket(wsUrl("/api/ws/stream"));
      wsRef.current = ws;

      ws.onopen = () => {
        lastMessageAt = Date.now();
        setWsConnected(true);
      };
      ws.onclose = () => {
        setWsConnected(false);
        reconnectTimer = setTimeout(connectWs, 2000);
      };
      ws.onerror = () => ws.close();
      ws.onmessage = async (ev) => {
        lastMessageAt = Date.now();
        try {
          const msg = JSON.parse(ev.data as string);
          if (msg.type === "snapshot") {
            const snap = msg as WsSnapshot;
            setSummary(snap.summary);

            // Для повного оновлення objects (з координатами + telemetry) — RTT fetch
            try {
              const objects = await api.dashboardFull();
              setObjects(objects as ObjectState[]);
            } catch {
              // fallback: обновити лише status/score з snapshot
            }
            try {
              const routing = await api.routing(5);
              setRouting(routing);
            } catch {
              /* ignore */
            }
            try {
              const scenario = await api.activeScenario();
              setActiveScenario(scenario as Scenario | null);
            } catch {
              /* ignore */
            }
            // assignments із snapshot
            if (Array.isArray(snap.assignments)) {
              setAssignments(snap.assignments as Assignment[]);
            } else {
              try {
                const a = await api.assignments();
                setAssignments(a);
              } catch {
                /* ignore */
              }
            }
          } else if (msg.type === "scenario_change") {
            // Миттєвий push зміни сценарію — не чекаємо 3с snapshot
            setActiveScenario((msg.scenario as Scenario | null) ?? null);
          } else if (msg.type === "event" && msg.event) {
            // Realtime push нової події в журнал (без polling)
            appendEvent(msg.event as BoltEvent);
          } else if (msg.type === "assignment") {
            // Миттєвий push призначення (відправлено / прибуло / скасовано)
            try {
              const a = await api.assignments();
              setAssignments(a);
            } catch {
              /* ignore */
            }
          }
        } catch {
          /* ignore malformed */
        }
      };
    }

    bootstrap().then(connectWs);

    // Watchdog: якщо від сервера >20с тиші при "відкритому" сокеті —
    // з'єднання зомбі. Закриваємо примусово → onclose → реконект.
    const watchdog = setInterval(() => {
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN && Date.now() - lastMessageAt > 20000) {
        ws.close();
      }
    }, 5000);

    // Повернення на вкладку (розбудили ноутбук, розгорнули браузер):
    // одразу перетягуємо свіжий стан і перевіряємо живість сокета.
    const onVisible = () => {
      if (document.visibilityState !== "visible") return;
      bootstrap();
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN && Date.now() - lastMessageAt > 10000) {
        ws.close();
      }
    };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      cancelled = true;
      clearTimeout(reconnectTimer);
      clearInterval(watchdog);
      document.removeEventListener("visibilitychange", onVisible);
      wsRef.current?.close();
    };
  }, []);

  return <>{children}</>;
}