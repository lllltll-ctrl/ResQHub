// API-клієнт для ResQHub backend
import { apiUrl } from "./config";
import type {
  Assignment,
  BoltEvent,
  CityObject,
  DashboardSummary,
  ObjectState,
  PublicObject,
  RoutingRecommendation,
  Scenario,
  Score,
} from "./types";

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(apiUrl(path), { cache: "no-store" });
  if (!res.ok) throw new Error(`${path}: ${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(apiUrl(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${path}: ${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

export const api = {
  objects: () => getJson<CityObject[]>("/api/objects"),
  objectsByDistrict: (district: string) =>
    getJson<CityObject[]>(`/api/objects?district=${encodeURIComponent(district)}`),
  object: (id: string) => getJson<CityObject>(`/api/objects/${id}`),

  dashboard: () => getJson<DashboardSummary>("/api/dashboard"),
  dashboardFull: () => getJson<ObjectState[]>("/api/dashboard/full"),

  routing: (limit = 5) => getJson<RoutingRecommendation[]>(`/api/routing?limit=${limit}`),

  assignments: () => getJson<Assignment[]>("/api/assignments"),
  createAssignment: (object_id: string, resource_type: string, eta_min = 30) =>
    postJson<Assignment>("/api/assignments", { object_id, resource_type, eta_min }),

  startScenario: (type: string, scope = "CITY", target: string | null = null, intensity = 1.0) =>
    postJson<Scenario>("/api/scenarios", { type, scope, target, intensity }),
  activeScenario: () => getJson<Scenario | null>("/api/scenarios/active"),

  events: (limit = 50) => getJson<BoltEvent[]>(`/api/events?limit=${limit}`),

  briefing: (object_id: string, use_llm = false) =>
    getJson<Briefing>(`/api/briefing/${object_id}?use_llm=${use_llm}`),

  counterfactual: (
    object_id: string,
    intervention_type: string,
    eta_min = 30,
  ) =>
    postJson<Counterfactual>(
      `/api/counterfactual/${object_id}?intervention_type=${intervention_type}&eta_min=${eta_min}`,
      {},
    ),

  modelCards: () => getJson<ModelCard[]>(`/api/models/cards`),
  modelHealth: () => getJson<ModelHealth>(`/api/models/health`),

  telemetry: (object_id: string, limit = 50) =>
    getJson<unknown[]>(`/api/telemetry/${object_id}?limit=${limit}`),
  scores: (object_id: string, limit = 50) => getJson<Score[]>(`/api/scores/${object_id}?limit=${limit}`),

  publicObjects: (lat: number, lon: number, radius_m = 2000) =>
    getJson<PublicObject[]>(`/api/public/objects?lat=${lat}&lon=${lon}&radius_m=${radius_m}`),
};