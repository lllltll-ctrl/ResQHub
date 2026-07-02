"""
Pydantic v2 схеми (DTO) для API ResQHub.
Відокремлюють ORM-моделі від зовнішнього контракту.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer


def _to_utc_iso(dt: datetime) -> str:
    """Серіалізує datetime у ISO з таймзоною UTC.

    SQLite зберігає час як naive-UTC (без tzinfo). Якщо віддати його клієнту
    без 'Z'/offset, браузер трактує його як ЛОКАЛЬНИЙ → історія «зсувається»
    на різницю з UTC (для України −2/−3 год). Тегуємо naive як UTC.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


# datetime, який завжди серіалізується як UTC-aware ISO рядок.
UtcDatetime = Annotated[datetime, PlainSerializer(_to_utc_iso, return_type=str)]

# Note: використовуємо str замість Literal[...] для output-схем, бо SQLAlchemy
# повертає Python Enum, який не валідується як Literal. Для input-схем Literal OK.
ObjectT = Literal["SHELTER", "SCHOOL", "RESILIENCE_POINT", "HOSPITAL", "FIRE_STATION"]
CriticalityT = Literal[1, 2, 3, 4, 5]
StatusT = Literal["STABLE", "WARNING", "CRITICAL", "RESCUE_IN_TRANSIT"]
ScenarioTypeT = Literal["NORMAL", "BLACKOUT", "PARTIAL_OUTAGE", "SIGNAL_DOWN", "RESET"]
ScenarioScopeT = Literal["CITY", "DISTRICT", "OBJECT"]
ResourceTypeT = Literal["GENERATOR", "BATTERY_BANK", "STARLINK", "TECH_TEAM", "FUEL"]
AssignmentStatusT = Literal["REQUESTED", "DISPATCHED", "ARRIVED", "CANCELLED"]

StatusOutT = str
ObjectTypeOutT = str
CriticalityOutT = int
ScenarioTypeOutT = str
ScenarioScopeOutT = str
ResourceTypeOutT = str
AssignmentStatusOutT = str


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ObjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    type: ObjectT
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    district: str = Field(min_length=1, max_length=100)
    address: str = ""
    criticality: CriticalityT = 3
    capacity: int = Field(default=100, ge=1)
    battery_capacity_wh: float = Field(default=5000.0, ge=0)
    has_generator: bool = False
    has_starlink: bool = False


class ObjectOut(ORMBase):
    id: uuid.UUID
    name: str
    type: ObjectTypeOutT
    lat: float
    lon: float
    district: str
    address: str
    criticality: CriticalityOutT
    capacity: int
    battery_capacity_wh: float
    has_generator: bool
    has_starlink: bool
    created_at: UtcDatetime


class TelemetryCreate(BaseModel):
    object_id: uuid.UUID
    power_on: bool = True
    battery_pct: float = Field(default=100.0, ge=0, le=100)
    battery_est_hours: float = Field(default=24.0, ge=0)
    temp_c: float = 21.0
    humidity_pct: float = Field(default=45.0, ge=0, le=100)
    co2_ppm: float = Field(default=600.0, ge=0)
    signal: int = Field(default=4, ge=0, le=4)
    internet_on: bool = True
    occupancy: int = Field(default=0, ge=0)
    generator_on: bool = False
    scenario_id: uuid.UUID | None = None


class TelemetryOut(ORMBase):
    id: uuid.UUID
    object_id: uuid.UUID
    ts: UtcDatetime
    power_on: bool
    battery_pct: float
    battery_est_hours: float
    temp_c: float
    humidity_pct: float
    co2_ppm: float
    signal: int
    internet_on: bool
    occupancy: int
    generator_on: bool


class ScoreOut(ORMBase):
    id: uuid.UUID
    object_id: uuid.UUID
    ts: UtcDatetime
    score: float = Field(ge=0, le=100)
    status: StatusT
    time_to_critical_min: float | None
    components: dict


class ScenarioCreate(BaseModel):
    type: ScenarioTypeT
    scope: ScenarioScopeT = "CITY"
    target: str | None = None
    intensity: float = Field(default=1.0, ge=0, le=1)


class ScenarioOut(ORMBase):
    id: uuid.UUID
    type: ScenarioTypeOutT
    scope: ScenarioScopeOutT
    target: str | None
    intensity: float
    started_at: UtcDatetime
    ended_at: UtcDatetime | None
    is_active: bool


class AssignmentCreate(BaseModel):
    object_id: uuid.UUID
    resource_type: ResourceTypeT
    eta_min: int = Field(default=30, ge=0)


class AssignmentOut(ORMBase):
    id: uuid.UUID
    object_id: uuid.UUID
    resource_type: ResourceTypeOutT
    status: AssignmentStatusOutT
    eta_min: int
    priority_score: float
    justification: str
    created_at: UtcDatetime


class EventOut(ORMBase):
    id: uuid.UUID
    ts: UtcDatetime
    object_id: uuid.UUID | None
    scenario_id: uuid.UUID | None
    type: str
    message: str
    severity: str


class RoutingRecommendation(BaseModel):
    """Рекомендація маршрутизації ресурсів — ключова фіча для журі."""

    object_id: uuid.UUID
    object_name: str
    object_type: ObjectT
    district: str
    priority_score: float = Field(ge=0, le=100)
    current_score: float
    current_status: StatusT
    time_to_critical_min: float | None
    criticality: CriticalityT
    occupancy: int
    capacity: int
    justification: str


class DashboardSummary(BaseModel):
    """Загальний стан системи для головного екрану дашборду."""

    total_objects: int
    stable: int
    warning: int
    critical: int
    rescue_in_transit: int
    avg_city_score: float
    active_scenarios: int
    active_assignments: int


class PublicObjectOut(BaseModel):
    """Скорочене представлення об'єкта для мешканського UI."""

    id: uuid.UUID
    name: str
    type: ObjectT
    lat: float
    lon: float
    address: str
    status: StatusT
    power_on: bool
    internet_on: bool
    occupancy: int
    capacity: int
    distance_m: float | None = None
