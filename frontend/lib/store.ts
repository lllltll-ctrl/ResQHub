// Zustand store for global UI state
import { create } from "zustand";
import type {
  DashboardSummary,
  ObjectState,
  RoutingRecommendation,
  Scenario,
  BoltEvent,
  Assignment,
} from "./types";

interface AppState {
  // Data
  summary: DashboardSummary | null;
  objects: ObjectState[];
  routing: RoutingRecommendation[];
  assignments: Assignment[];
  activeScenario: Scenario | null;
  events: BoltEvent[];
  eventsClearedAt: number | null;

  // UI
  selectedObjectId: string | null;
  panel: "dashboard" | "analytics" | "resident" | "demo";
  wsConnected: boolean;

  // Setters
  setSummary: (s: DashboardSummary) => void;
  setObjects: (o: ObjectState[]) => void;
  setRouting: (r: RoutingRecommendation[]) => void;
  setAssignments: (a: Assignment[]) => void;
  setActiveScenario: (s: Scenario | null) => void;
  setEvents: (e: BoltEvent[]) => void;
  appendEvent: (e: BoltEvent) => void;
  clearEvents: () => void;
  setSelectedObjectId: (id: string | null) => void;
  setPanel: (p: AppState["panel"]) => void;
  setWsConnected: (c: boolean) => void;
}

export const useStore = create<AppState>((set) => ({
  summary: null,
  objects: [],
  routing: [],
  assignments: [],
  activeScenario: null,
  events: [],
  eventsClearedAt: null,
  selectedObjectId: null,
  panel: "dashboard",
  wsConnected: false,

  setSummary: (s) => set({ summary: s }),
  setObjects: (o) => set({ objects: o }),
  setRouting: (r) => set({ routing: r }),
  setAssignments: (a) => set({ assignments: a }),
  setActiveScenario: (s) => set({ activeScenario: s }),
  setEvents: (e) => set({ events: e }),
  appendEvent: (e) =>
    set((st) => {
      // Дедуплікація за id — WS може прислати ту ж подію, що вже в initial bootstrap.
      if (st.events.some((x) => x.id === e.id)) return st;
      // Якщо користувач очищав журнал — ігноруємо події, що "прилетіли" з минулого.
      if (st.eventsClearedAt) {
        const clearedMs = st.eventsClearedAt;
        const evMs = new Date(e.ts).getTime();
        if (evMs < clearedMs) return st;
      }
      return { events: [e, ...st.events].slice(0, 100), eventsClearedAt: null };
    }),
  clearEvents: () => set({ events: [], eventsClearedAt: Date.now() }),
  setSelectedObjectId: (id) => set({ selectedObjectId: id }),
  setPanel: (p) => set({ panel: p }),
  setWsConnected: (c) => set({ wsConnected: c }),
}));