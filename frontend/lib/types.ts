// Резидентні TypeScript типи що відповідають backend API (PYTHON SCHEMAS)

export type ObjectTypeT = "SHELTER" | "SCHOOL" | "RESILIENCE_POINT" | "HOSPITAL" | "FIRE_STATION";
export type CriticalityT = 1 | 2 | 3 | 4 | 5;
export type StatusT = "STABLE" | "WARNING" | "CRITICAL" | "RESCUE_IN_TRANSIT";
export type ScenarioTypeT = "NORMAL" | "BLACKOUT" | "PARTIAL_OUTAGE" | "SIGNAL_DOWN" | "RESET";
export type ScenarioScopeT = "CITY" | "DISTRICT" | "OBJECT";
export type ResourceTypeT = "GENERATOR" | "BATTERY_BANK" | "STARLINK" | "TECH_TEAM" | "FUEL";
export type AssignmentStatusT = "REQUESTED" | "DISPATCHED" | "ARRIVED" | "CANCELLED";

export interface CityObject {
  id: string;
  name: string;
  type: ObjectTypeT;
  lat: number;
  lon: number;
  district: string;
  address: string;
  criticality: CriticalityT;
  capacity: number;
  battery_capacity_wh: number;
  has_generator: boolean;
  has_starlink: boolean;
  created_at: string;
}

export interface Telemetry {
  power_on: boolean;
  battery_pct: number;
  battery_est_hours: number;
  temp_c: number;
  humidity_pct: number;
  co2_ppm: number;
  signal: number;
  internet_on: boolean;
  occupancy: number;
  generator_on: boolean;
  ts: string;
}

export interface Score {
  score: number;
  status: StatusT;
  time_to_critical_min: number | null;
  components: Record<string, unknown>;
  ts: string;
}

export interface ObjectState {
  id: string;
  name: string;
  type: ObjectTypeT;
  lat: number;
  lon: number;
  district: string;
  address: string;
  criticality: CriticalityT;
  capacity: number;
  has_generator: boolean;
  has_starlink: boolean;
  telemetry: Telemetry | null;
  score: Score | null;
}

export interface DashboardSummary {
  total_objects: number;
  stable: number;
  warning: number;
  critical: number;
  rescue_in_transit: number;
  avg_city_score: number;
  active_scenarios: number;
  active_assignments: number;
}

export interface RoutingRecommendation {
  object_id: string;
  object_name: string;
  object_type: ObjectTypeT;
  district: string;
  priority_score: number;
  current_score: number;
  current_status: StatusT;
  time_to_critical_min: number | null;
  criticality: CriticalityT;
  occupancy: number;
  capacity: number;
  justification: string;
}

export interface Assignment {
  id: string;
  object_id: string;
  resource_type: ResourceTypeT;
  status: AssignmentStatusT;
  eta_min: number;
  priority_score: number;
  justification: string;
  created_at: string;
}

export interface Scenario {
  id: string;
  type: ScenarioTypeT;
  scope: ScenarioScopeT;
  target: string | null;
  intensity: number;
  started_at: string;
  ended_at: string | null;
  is_active: boolean;
}

export interface BoltEvent {
  id: string;
  ts: string;
  object_id: string | null;
  scenario_id: string | null;
  type: string;
  message: string;
  severity: "INFO" | "WARNING" | "ERROR";
}

export interface PublicObject {
  id: string;
  name: string;
  type: ObjectTypeT;
  lat: number;
  lon: number;
  address: string;
  status: StatusT;
  power_on: boolean;
  internet_on: boolean;
  occupancy: number;
  capacity: number;
  distance_m: number | null;
}

export interface WsSnapshot {
  type: "snapshot";
  summary: DashboardSummary;
  objects: Array<{
    id: string;
    name: string;
    status: StatusT;
    score: number | null;
    battery_pct: number | null;
    power_on: boolean | null;
    occupancy: number;
    ts: string | null;
  }>;
}

export type StatusColor = "ok" | "warn" | "crit" | "rescue";

export const STATUS_COLOR: Record<StatusT, StatusColor> = {
  STABLE: "ok",
  WARNING: "warn",
  CRITICAL: "crit",
  RESCUE_IN_TRANSIT: "rescue",
};

export const STATUS_LABEL_UA: Record<StatusT, string> = {
  STABLE: "Стабільно",
  WARNING: "Увага",
  CRITICAL: "Критично",
  RESCUE_IN_TRANSIT: "Допомога в дорозі",
};

export const OBJECT_TYPE_UA: Record<ObjectTypeT, string> = {
  SHELTER: "Укриття",
  SCHOOL: "Школа",
  RESILIENCE_POINT: "Пункт незламності",
  HOSPITAL: "Лікарня",
  FIRE_STATION: "Пожежна частина",
};

export const RESOURCE_TYPE_UA: Record<ResourceTypeT, string> = {
  GENERATOR: "Генератор",
  BATTERY_BANK: "Батарея",
  STARLINK: "Starlink",
  TECH_TEAM: "Техбригада",
  FUEL: "Паливо",
};

export const SCENARIO_TYPE_UA: Record<ScenarioTypeT, string> = {
  NORMAL: "Нормальний",
  BLACKOUT: "Блекаут",
  PARTIAL_OUTAGE: "Часткове відключення",
  SIGNAL_DOWN: "Зв'язок відсутній",
  RESET: "Скидання",
};

export const SCENARIO_SCOPE_UA: Record<ScenarioScopeT, string> = {
  CITY: "Місто",
  DISTRICT: "Район",
  OBJECT: "Об'єкт",
};

export const ASSIGNMENT_STATUS_UA: Record<AssignmentStatusT, string> = {
  REQUESTED: "Запитано",
  DISPATCHED: "Відправлено",
  ARRIVED: "Прибуло",
  CANCELLED: "Скасовано",
};

export const SCORE_COMPONENT_UA: Record<string, string> = {
  power: "Електроживлення",
  internet: "Інтернет",
  occupancy: "Заповненість",
  battery: "Батарея",
  generator: "Генератор",
  temperature: "Температура",
  co2: "CO₂",
  signal: "Сигнал",
  humidity: "Вологість",
  ml_feature_battery: "Заряд батареї",
  ml_feature_temp: "Температура",
  ml_feature_co2: "Рівень CO₂",
  ml_feature_occupancy_ratio: "Коефіцієнт заповненості",
  ml_feature_criticality: "Критичність об'єкта",
  ml_prediction_confidence: "Впевненість прогнозу",
  generator_bonus: "Бонус генератора",
  starlink_bonus: "Бонус Starlink",
  forecast_slope_pct_per_min: "Зміна прогнозу (%/хв)",
  forecast_confidence: "Впевненість прогнозу",
};

export interface BriefingKeyFactor {
  feature: string;
  contribution: number;
}

export interface Briefing {
  summary: string;
  severity: "STABLE" | "WARNING" | "CRITICAL";
  recommended_actions: string[];
  key_factors: BriefingKeyFactor[];
  model_confidence: number;
  method: "template" | "llm";
  object_id: string;
  object_name: string;
  object_type: string;
  ml_score: number;
  ml_status: StatusT;
  ttc_minutes: number | null;
  anomaly_detected: boolean;
  anomaly_score: number | null;
  drift_detected: boolean;
}

export type InterventionTypeT =
  | "generator"
  | "tech_team"
  | "starlink"
  | "fuel"
  | "evacuation";

export interface CounterfactualFeatureChange {
  feature: string;
  before: number;
  after: number;
  delta: number;
}

export interface Counterfactual {
  object_id: string;
  object_name: string;
  object_type: string;
  intervention_type: InterventionTypeT;
  intervention_label: string;
  eta_min: number;
  before: {
    score: number;
    status: string;
    ttc_min: number | null;
  };
  after: {
    score: number;
    status: string;
    ttc_min: number | null;
  };
  score_delta: number;
  ttc_delta_min: number | null;
  will_rescue: boolean;
  top_feature_changes: CounterfactualFeatureChange[];
  recommendation: string;
}

export interface ModelCard {
  model_name: string;
  model_version: string;
  model_type: string;
  intended_use: string;
  training_data: string;
  features: string[];
  target: string;
  metrics: Record<string, number>;
  limitations: string[];
  ethical_considerations: string[];
  created_at: number;
  updated_at: number;
  owner: string;
  contact: string;
}

export interface ModelHealthArtifact {
  trained_at?: string;
  n_samples?: number;
  metrics?: Record<string, number>;
}

export interface ModelHealth {
  models: Record<string, string>;
  online_learner: {
    is_loaded: boolean;
    is_warm: boolean;
    n_observations: number;
    n_drifts_detected: number;
    last_drift_at: number | null;
    recent_mae: number | null;
    baseline_mae: number;
    model_version: string;
  };
  artifacts: Record<string, ModelHealthArtifact>;
}

export interface DriftFeature {
  feature: string;
  statistic: number;
  p_value: number;
  drifted: boolean;
  current_mean: number;
  reference_mean: number;
}

export interface DriftStatus {
  n_observations: number;
  has_reference: boolean;
  drift_detected: boolean;
  n_drifted_features: number;
  features: DriftFeature[];
  checked_at: string;
  error?: string;
}