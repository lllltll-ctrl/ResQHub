"""
Service-оркестратор: поєднує телеметрію, score engine, forecast engine,
зберігає результат у БД і повертає prepared DTO.
Це єдине місце, що спеціальне пишеться у БД при новій телеметрії.

P0/P1 refactor:
  - Використовує натреновану ML-модель з app.ml.inference
  - ML-ranker для priority_score (app.ml.routing_ml)
  - Batch queries (N+1 fix) у get_dashboard_summary, get_routing_recommendations
  - Haversine distance у routing_engine
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import numpy as np
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models.domain import (
    Assignment,
    AssignmentStatus,
    Event,
    EventSeverity,
    EventType,
    Object,
    ResourceType,
    Score,
    ScoreStatus,
    Scenario,
    ScenarioScope,
    ScenarioType,
    Telemetry,
)
from app.schemas import (
    AssignmentCreate,
    ObjectCreate,
    RoutingRecommendation,
    ScenarioCreate,
    ScoreOut,
    TelemetryCreate,
)
from app.services.forecast_engine import (
    ForecastResult,
    TelemetryPoint,
    forecast_time_to_critical,
)
from app.services.routing_engine import (
    build_justification,
    compute_priority_score,
    optimize_generator_allocation,
)
from app.services.score_engine import ScoreInput, compute_score
from app.ml.routing_ml import predict_assignment_priority

logger = logging.getLogger(__name__)

TELEMETRY_HISTORY_FOR_FORECAST = 24
TOP_ROUTING_LIMIT = 5

# ── Модель енергоспоживання ─────────────────────────────────────────
# Базове навантаження об'єкта (Вт) за типом + споживання на людину.
# Автономність = battery_capacity_wh * pct / load — тому кожен об'єкт
# входить у блекаут зі СВОЄЮ швидкістю деградації, а не з магічною
# константою для всіх.
_BASE_LOAD_W = {
    "HOSPITAL": 4000.0,
    "FIRE_STATION": 1500.0,
    "SCHOOL": 800.0,
    "SHELTER": 600.0,
    "RESILIENCE_POINT": 400.0,
}
_LOAD_PER_PERSON_W = 25.0

# Запас пального стаціонарного генератора (год) за типом об'єкта.
_GENERATOR_FUEL_HOURS = {
    "HOSPITAL": 48.0,
    "FIRE_STATION": 24.0,
    "RESILIENCE_POINT": 12.0,
    "SHELTER": 8.0,
    "SCHOOL": 8.0,
}


def estimate_backup_hours(obj: Object, battery_pct: float, occupancy: int) -> float:
    """Реальна автономність батареї (год) з поточним навантаженням."""
    base = _BASE_LOAD_W.get(obj.type.value, 800.0)
    load_w = base + occupancy * _LOAD_PER_PERSON_W
    energy_wh = obj.battery_capacity_wh * max(0.0, battery_pct) / 100.0
    return round(energy_wh / max(load_w, 1.0), 2)

_RESOURCE_TYPE_UA = {
    "GENERATOR": "Генератор",
    "BATTERY_BANK": "Батарея",
    "STARLINK": "Starlink",
    "TECH_TEAM": "Техбригада",
    "FUEL": "Паливо",
}

_STATUS_UA = {
    "STABLE": "Стабільно",
    "WARNING": "Увага",
    "CRITICAL": "Критично",
    "RESCUE_IN_TRANSIT": "Допомога в дорозі",
}

_SCENARIO_TYPE_UA = {
    "NORMAL": "Нормальний",
    "BLACKOUT": "Блекаут",
    "PARTIAL_OUTAGE": "Часткове відключення",
    "SIGNAL_DOWN": "Зв'язок відсутній",
    "RESET": "Скидання",
}

_SCENARIO_SCOPE_UA = {
    "CITY": "Місто",
    "DISTRICT": "Район",
    "OBJECT": "Об'єкт",
}


def create_object(db: Session, payload: ObjectCreate) -> Object:
    obj = Object(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def get_objects(db: Session, district: str | None = None) -> list[Object]:
    stmt = select(Object).order_by(Object.name)
    if district:
        stmt = stmt.where(Object.district == district)
    return list(db.scalars(stmt))


def get_object(db: Session, object_id: uuid.UUID) -> Object | None:
    return db.get(Object, object_id)


def ingest_telemetry(db: Session, payload: TelemetryCreate) -> Telemetry:
    """Зберігає телеметрію, рахує score + forecast, зберігає score."""
    obj = db.get(Object, payload.object_id)
    if obj is None:
        raise ValueError(f"Object {payload.object_id} not found")

    t = Telemetry(
        object_id=payload.object_id,
        power_on=payload.power_on,
        battery_pct=payload.battery_pct,
        battery_est_hours=payload.battery_est_hours,
        temp_c=payload.temp_c,
        humidity_pct=payload.humidity_pct,
        co2_ppm=payload.co2_ppm,
        signal=payload.signal,
        internet_on=payload.internet_on,
        occupancy=payload.occupancy,
        generator_on=payload.generator_on,
        scenario_id=payload.scenario_id,
    )
    db.add(t)
    db.flush()

    score_result = compute_score(
        ScoreInput(
            battery_pct=payload.battery_pct,
            battery_est_hours=payload.battery_est_hours,
            power_on=payload.power_on,
            temp_c=payload.temp_c,
            co2_ppm=payload.co2_ppm,
            signal=payload.signal,
            internet_on=payload.internet_on,
            occupancy=payload.occupancy,
            capacity=obj.capacity,
            criticality=obj.criticality,
            has_generator=obj.has_generator,
            has_starlink=obj.has_starlink,
            generator_on=payload.generator_on,
            humidity_pct=payload.humidity_pct,
        )
    )

    forecast = _forecast_for_object(db, payload.object_id)

    status = score_result.status
    # Якщо батарея ось-ось розрядиться (<60 хв), status піднімаємо до CRITICAL,
    # навіть якщо score ще "пристойний". Бо score — це зріз, а ttc — прогноз.
    ttc = forecast.time_to_critical_min
    if ttc is not None and ttc < 30:
        status = ScoreStatus.CRITICAL
    elif ttc is not None and ttc < 60 and status == ScoreStatus.STABLE:
        status = ScoreStatus.WARNING
    # Втрата зв'язку — це операційна проблема (об'єкт "сліпий" для координації).
    # Навіть якщо живлення в нормі, диспетчер має звернути увагу → щонайменше
    # WARNING, щоб було видно потребу в Starlink.
    powered = payload.power_on or payload.generator_on
    if not payload.internet_on and powered and status == ScoreStatus.STABLE:
        status = ScoreStatus.WARNING
    if _has_active_assignment(db, payload.object_id):
        status = ScoreStatus.RESCUE_IN_TRANSIT

    score = Score(
        object_id=payload.object_id,
        score=score_result.score,
        status=status,
        time_to_critical_min=forecast.time_to_critical_min,
        components={
            **score_result.components,
            "forecast_slope_pct_per_min": forecast.slope_pct_per_min,
            "forecast_confidence": forecast.confidence,
        },
    )
    db.add(score)
    db.flush()
    db.refresh(score)

    _maybe_emit_status_event(db, obj, score)
    db.commit()
    db.refresh(t)
    return t


def _forecast_for_object(db: Session, object_id: uuid.UUID) -> ForecastResult:
    stmt = (
        select(Telemetry)
        .where(Telemetry.object_id == object_id)
        .order_by(desc(Telemetry.ts))
        .limit(TELEMETRY_HISTORY_FOR_FORECAST)
    )
    rows = list(db.scalars(stmt))[::-1]
    points = [
        TelemetryPoint(
            ts=r.ts.timestamp(),
            battery_pct=r.battery_pct,
            power_on=r.power_on,
            battery_est_hours=r.battery_est_hours,
            generator_on=r.generator_on,
        )
        for r in rows
    ]
    return forecast_time_to_critical(points)


def get_latest_telemetry(db: Session, object_id: uuid.UUID) -> Telemetry | None:
    stmt = (
        select(Telemetry)
        .where(Telemetry.object_id == object_id)
        .order_by(desc(Telemetry.ts))
        .limit(1)
    )
    return db.scalars(stmt).first()


def get_latest_score(db: Session, object_id: uuid.UUID) -> Score | None:
    stmt = (
        select(Score)
        .where(Score.object_id == object_id)
        .order_by(desc(Score.ts))
        .limit(1)
    )
    return db.scalars(stmt).first()


def get_objects_with_state(db: Session) -> list[dict]:
    """Об'єкти разом з останньою телеметрією/скорою (для дашборду).

    P1 refactor: виконує batch-запити для уникнення N+1.
    """
    objects = get_objects(db)
    if not objects:
        return []

    object_ids = [obj.id for obj in objects]

    # Batch: остання telemetry для кожного object_id
    last_telem_subq = (
        select(
            Telemetry.object_id,
            func.max(Telemetry.ts).label("max_ts"),
        )
        .where(Telemetry.object_id.in_(object_ids))
        .group_by(Telemetry.object_id)
        .subquery()
    )
    last_telems = list(
        db.scalars(
            select(Telemetry).join(
                last_telem_subq,
                (Telemetry.object_id == last_telem_subq.c.object_id)
                & (Telemetry.ts == last_telem_subq.c.max_ts),
            )
        )
    )
    telem_by_obj = {t.object_id: t for t in last_telems}

    # Batch: останній score для кожного object_id
    last_score_subq = (
        select(
            Score.object_id,
            func.max(Score.ts).label("max_ts"),
        )
        .where(Score.object_id.in_(object_ids))
        .group_by(Score.object_id)
        .subquery()
    )
    last_scores = list(
        db.scalars(
            select(Score).join(
                last_score_subq,
                (Score.object_id == last_score_subq.c.object_id)
                & (Score.ts == last_score_subq.c.max_ts),
            )
        )
    )
    score_by_obj = {s.object_id: s for s in last_scores}

    out: list[dict] = []
    for obj in objects:
        out.append(
            {
                "object": obj,
                "telemetry": telem_by_obj.get(obj.id),
                "score": score_by_obj.get(obj.id),
            }
        )
    return out


def get_routing_recommendations(
    db: Session, limit: int = TOP_ROUTING_LIMIT
) -> list[RoutingRecommendation]:
    """Топ-N об'єктів для направлення ресурсу — killer screen.

    P1 refactor:
      - ML-ranker (LightGBM) замість hand-tuned формули для priority_score
      - Об'єкти з активним живленням (мережа/генератор) виключені
      - Batch telemetry/score queries (N+1 fix)
      - Haversine distance у routing_engine.optimize_generator_allocation
    """
    objects = get_objects(db)
    if not objects:
        return []

    object_ids = [obj.id for obj in objects]

    # Batch: остання telemetry
    last_telem_subq = (
        select(
            Telemetry.object_id,
            func.max(Telemetry.ts).label("max_ts"),
        )
        .where(Telemetry.object_id.in_(object_ids))
        .group_by(Telemetry.object_id)
        .subquery()
    )
    last_telems = list(
        db.scalars(
            select(Telemetry).join(
                last_telem_subq,
                (Telemetry.object_id == last_telem_subq.c.object_id)
                & (Telemetry.ts == last_telem_subq.c.max_ts),
            )
        )
    )
    telem_by_obj = {t.object_id: t for t in last_telems}

    # Batch: останній score
    last_score_subq = (
        select(
            Score.object_id,
            func.max(Score.ts).label("max_ts"),
        )
        .where(Score.object_id.in_(object_ids))
        .group_by(Score.object_id)
        .subquery()
    )
    last_scores = list(
        db.scalars(
            select(Score).join(
                last_score_subq,
                (Score.object_id == last_score_subq.c.object_id)
                & (Score.ts == last_score_subq.c.max_ts),
            )
        )
    )
    score_by_obj = {s.object_id: s for s in last_scores}

    candidates: list[RoutingRecommendation] = []
    opt_data = []

    for obj in objects:
        last_s = score_by_obj.get(obj.id)
        last_t = telem_by_obj.get(obj.id)
        if last_s is None or last_t is None:
            continue
        if last_s.status == ScoreStatus.RESCUE_IN_TRANSIT:
            continue
        if last_s.status == ScoreStatus.STABLE and last_s.time_to_critical_min is None:
            continue

        # Об'єкт з живленням (мережа або працюючий генератор) допомоги
        # не потребує. Якщо генератор заглухне (пальне) — generator_on
        # стане False і об'єкт знову з'явиться у кандидатах.
        if last_t.power_on or last_t.generator_on:
            continue

        # ML-based priority через LightGBM ranker
        try:
            priority = predict_assignment_priority(
                current_score=last_s.score,
                time_to_critical_min=last_s.time_to_critical_min,
                criticality=obj.criticality,
                occupancy=last_t.occupancy,
                capacity=obj.capacity,
                battery_pct=last_t.battery_pct,
                has_generator=obj.has_generator,
                has_starlink=obj.has_starlink,
                power_on=last_t.power_on,
            )
        except Exception as e:
            # Fallback на hand-tuned формулу якщо ML-модель недоступна
            logger.warning("ML ranker failed, falling back to heuristic: %s", e)
            priority = compute_priority_score(
                current_score=last_s.score,
                time_to_critical_min=last_s.time_to_critical_min,
                criticality=obj.criticality,
                occupancy=last_t.occupancy,
                capacity=obj.capacity,
            )

        justification = build_justification(
            obj.name,
            last_s.score,
            last_s.status,
            last_s.time_to_critical_min,
            obj.criticality,
            last_t.occupancy,
            obj.capacity,
        )

        candidates.append(
            RoutingRecommendation(
                object_id=obj.id,
                object_name=obj.name,
                object_type=obj.type.value,
                district=obj.district,
                priority_score=priority,
                current_score=last_s.score,
                current_status=last_s.status.value,
                time_to_critical_min=last_s.time_to_critical_min,
                criticality=obj.criticality,
                occupancy=last_t.occupancy,
                capacity=obj.capacity,
                justification=justification,
            )
        )
        opt_data.append((str(obj.id), obj.lat, obj.lon, priority))

    # Apply Hungarian Algorithm for optimal assignment
    assigned_ids = optimize_generator_allocation(opt_data, available_units=limit)

    # Boost priority score for assigned ones so they appear at the top
    for cand in candidates:
        if str(cand.object_id) in assigned_ids:
            cand.priority_score += 50.0  # Modest boost, not +1000
            cand.justification += " [ОПТИМІЗОВАНО: Призначено вільну техніку]"

    candidates.sort(key=lambda c: c.priority_score, reverse=True)
    return candidates[:limit]


def create_assignment(db: Session, payload: AssignmentCreate) -> Assignment:
    obj = db.get(Object, payload.object_id)
    if obj is None:
        raise ValueError(f"Object {payload.object_id} not found")
    last_s = get_latest_score(db, payload.object_id)
    last_t = get_latest_telemetry(db, payload.object_id) or None
    priority = 50.0
    time_to_critical_min: float | None = None
    occupancy = 0
    if last_s is not None:
        time_to_critical_min = last_s.time_to_critical_min
        if last_t is not None:
            occupancy = last_t.occupancy
        priority = compute_priority_score(
            current_score=last_s.score,
            time_to_critical_min=time_to_critical_min,
            criticality=obj.criticality,
            occupancy=occupancy,
            capacity=obj.capacity,
        )
    justification = build_justification(
        obj.name,
        last_s.score if last_s else 100.0,
        last_s.status if last_s else ScoreStatus.STABLE,
        time_to_critical_min,
        obj.criticality,
        occupancy,
        obj.capacity,
    )
    a = Assignment(
        object_id=payload.object_id,
        resource_type=payload.resource_type,
        status=AssignmentStatus.DISPATCHED,
        eta_min=payload.eta_min,
        priority_score=priority,
        justification=justification,
    )
    db.add(a)
    db.flush()
    resource_name = _RESOURCE_TYPE_UA.get(payload.resource_type, payload.resource_type)
    event = Event(
        object_id=obj.id,
        type=EventType.ASSIGNMENT,
        severity=EventSeverity.INFO,
        message=f"Призначено {resource_name} для {obj.name}. Прибуття через {payload.eta_min} хв.",
    )
    db.add(event)
    db.commit()
    db.refresh(a)
    return a


def get_active_assignments(db: Session) -> list[Assignment]:
    stmt = (
        select(Assignment)
        .where(
            Assignment.status.in_(
                [AssignmentStatus.DISPATCHED, AssignmentStatus.REQUESTED]
            )
        )
        .order_by(desc(Assignment.created_at))
    )
    return list(db.scalars(stmt))


def complete_assignment(
    db: Session, assignment_id: uuid.UUID, outcome: str = "success"
) -> Optional[Assignment]:
    """Завершує assignment: відмічає ARRIVED, логує event, застосовує ефект до об'єкта.

    outcome:
      - 'success' → ресурс спрацював, об'єкт повертається у звичайний режим
      - 'cancelled' → ресурс відкликано
    Після complete наступний telemetry-tick перерахує status поза RESCUE_IN_TRANSIT.
    """
    a = db.get(Assignment, assignment_id)
    if a is None:
        return None
    if a.status == AssignmentStatus.ARRIVED:
        return a
    a.status = AssignmentStatus.ARRIVED
    a.arrived_at = datetime.now(timezone.utc)

    obj = db.get(Object, a.object_id)
    if obj is None:
        db.commit()
        return a

    resource_name = _RESOURCE_TYPE_UA.get(a.resource_type.value, a.resource_type.value)

    if outcome == "success":
        effect_msg = f"{resource_name} доставлено на {obj.name}."
        last_t = get_latest_telemetry(db, obj.id)
        if last_t is not None:
            # Реалістичні ефекти ресурсів на об'єкт:
            # - GENERATOR: бригада увімкнула генератор (якщо він є).
            #   Живлення повертається, батарея заряджається.
            # - BATTERY_BANK: підключено зовнішню батарею. Тимчасове живлення.
            # - STARLINK: увімкнено термінал Starlink. Зв'язок відновлено.
            # - FUEL: заправлено генератор (4 год роботи). Працює ТІЛЬКИ якщо
            #   генератор увімкнений. Інакше — просто резерв пального.
            # - TECH_TEAM: ремонтні роботи. Універсальний, відновлює все,
            #   що можна відремонтувати.
            if a.resource_type == ResourceType.GENERATOR:
                # Мобільний генератор: після доставки об'єкт фактично має
                # генератор — фіксуємо це, щоб ML-модель і маршрутизація
                # бачили новий стан обладнання.
                if not obj.has_generator:
                    obj.has_generator = True
                new_power = last_t.power_on  # мережа як була (грід не наш)
                new_generator = True
                new_battery = min(100.0, last_t.battery_pct + 30.0)
                new_battery_hours = 48.0
                effect_msg = (
                    f"Генератор запущено на {obj.name}. "
                    f"Живлення від генератора, батарея заряджається."
                )
            elif a.resource_type == ResourceType.BATTERY_BANK:
                new_power = last_t.power_on  # мережу батарея не повертає
                new_generator = last_t.generator_on
                new_battery = min(100.0, last_t.battery_pct + 40.0)
                new_battery_hours = 8.0
                effect_msg = (
                    f"Зовнішня батарея підключена до {obj.name}. "
                    f"Тимчасове живлення на 8 год."
                )
            elif a.resource_type == ResourceType.STARLINK:
                # Мобільний термінал Starlink працює на будь-якому об'єкті
                if not obj.has_starlink:
                    obj.has_starlink = True
                new_power = last_t.power_on
                new_generator = last_t.generator_on
                new_battery = last_t.battery_pct
                new_battery_hours = last_t.battery_est_hours
                effect_msg = f"Starlink активовано на {obj.name}. Зв'язок відновлено."
            elif a.resource_type == ResourceType.FUEL:
                # Паливо має сенс тільки якщо на об'єкті є генератор.
                if obj.has_generator:
                    new_power = last_t.power_on
                    new_generator = True  # заправили та (пере)запустили
                    new_battery = min(100.0, last_t.battery_pct + 20.0)
                    new_battery_hours = max(last_t.battery_est_hours, 8.0)
                    effect_msg = (
                        f"Паливо залито в генератор на {obj.name}. "
                        f"Генератор працює, +8 годин роботи."
                    )
                else:
                    new_power = last_t.power_on
                    new_generator = False
                    new_battery = last_t.battery_pct
                    new_battery_hours = last_t.battery_est_hours
                    effect_msg = (
                        f"Паливо доставлено на {obj.name}, але генератора "
                        f"там немає. Потрібен мобільний генератор."
                    )
            elif a.resource_type == ResourceType.TECH_TEAM:
                # Техбригада усуває проблеми: запускає генератор, активує Starlink,
                # знижує CO₂ завдяки вентиляції.
                new_power = last_t.power_on
                new_generator = obj.has_generator
                new_battery = min(100.0, last_t.battery_pct + 15.0)
                new_battery_hours = 24.0
                effect_msg = (
                    f"Техбригада провела ремонт на {obj.name}. "
                    + (
                        "Генератор увімкнено. "
                        if obj.has_generator
                        else "Живлення стабілізовано. "
                    )
                    + "Starlink активовано."
                    if obj.has_starlink
                    else ""
                ).strip()
            else:
                new_power = last_t.power_on
                new_generator = last_t.generator_on
                new_battery = last_t.battery_pct
                new_battery_hours = last_t.battery_est_hours
                effect_msg = (
                    f"{resource_name} доставлено на {obj.name}, але не може "
                    f"бути застосований (об'єкт не має відповідного обладнання)."
                )

            new_payload = TelemetryCreate(
                object_id=obj.id,
                power_on=new_power,
                battery_pct=new_battery,
                battery_est_hours=new_battery_hours,
                temp_c=last_t.temp_c,
                humidity_pct=last_t.humidity_pct,
                # CO₂ знижується, якщо увімкнений генератор (вентиляція) або
                # приїхала техбригада
                co2_ppm=max(
                    400.0,
                    last_t.co2_ppm - 200.0
                    if a.resource_type
                    in (ResourceType.TECH_TEAM, ResourceType.GENERATOR)
                    else last_t.co2_ppm,
                ),
                signal=4
                if a.resource_type in (ResourceType.STARLINK, ResourceType.TECH_TEAM)
                and obj.has_starlink
                else last_t.signal,
                internet_on=(
                    True
                    if a.resource_type
                    in (ResourceType.STARLINK, ResourceType.TECH_TEAM)
                    and obj.has_starlink
                    else last_t.internet_on
                ),
                occupancy=last_t.occupancy,
                generator_on=new_generator,
                scenario_id=last_t.scenario_id,
            )
            ingest_telemetry(db, new_payload)

        event = Event(
            object_id=obj.id,
            type=EventType.MANUAL,
            severity=EventSeverity.INFO,
            message=effect_msg,
        )
        db.add(event)
    else:
        event = Event(
            object_id=obj.id,
            type=EventType.MANUAL,
            severity=EventSeverity.WARNING,
            message=f"{resource_name} скасовано для {obj.name}.",
        )
        db.add(event)

    db.commit()
    db.refresh(a)
    return a


def _has_active_assignment(db: Session, object_id: uuid.UUID) -> bool:
    stmt = (
        select(Assignment.id)
        .where(
            Assignment.object_id == object_id,
            Assignment.status.in_(
                [AssignmentStatus.DISPATCHED, AssignmentStatus.REQUESTED]
            ),
        )
        .limit(1)
    )
    return db.scalar(stmt) is not None


def _maybe_emit_status_event(db: Session, obj: Object, score: Score) -> None:
    """Логує status change якщо попередній score відрізнявся статусом."""
    prev_stmt = (
        select(Score)
        .where(Score.object_id == obj.id, Score.id != score.id)
        .order_by(desc(Score.ts))
        .limit(1)
    )
    prev = db.scalars(prev_stmt).first()
    if prev is None or prev.status == score.status:
        return
    severity = EventSeverity.INFO
    if score.status == ScoreStatus.CRITICAL:
        severity = EventSeverity.ERROR
    elif score.status == ScoreStatus.WARNING:
        severity = EventSeverity.WARNING
    status_name = _STATUS_UA.get(score.status.value, score.status.value)
    event = Event(
        object_id=obj.id,
        type=EventType.STATUS_CHANGE,
        severity=severity,
        message=f"{obj.name} → {status_name} (бал {score.score})",
    )
    db.add(event)


def _apply_scenario_immediately(db: Session, scenario: Scenario) -> None:
    """Негайно застосовує ефекти сценарію до телеметрії об'єктів.

    Це дає миттєву візуальну реакцію в UI, навіть якщо симулятор не запущений.
    """
    objects = get_objects(db)
    for obj in objects:
        if scenario.scope == ScenarioScope.OBJECT and str(obj.id) != (
            scenario.target or ""
        ):
            continue
        if scenario.scope == ScenarioScope.DISTRICT and obj.district != scenario.target:
            continue

        last_t = get_latest_telemetry(db, obj.id)
        base_battery = last_t.battery_pct if last_t else 100.0
        base_temp = last_t.temp_c if last_t else 21.0
        base_humidity = last_t.humidity_pct if last_t else 45.0
        base_co2 = last_t.co2_ppm if last_t else 600.0
        base_occupancy = last_t.occupancy if last_t else 0

        if scenario.type in (ScenarioType.BLACKOUT, ScenarioType.PARTIAL_OUTAGE):
            # Мережа зникає, але батарея НЕ обнуляється: кожен об'єкт входить
            # у блекаут зі своїм поточним зарядом і власною автономністю.
            power_on = False
            if obj.has_generator:
                # АВР (автоматичний ввід резерву): стаціонарний генератор
                # стартує сам, як у реальній лікарні. Такі об'єкти живуть
                # на пальному і НЕ потребують негайного втручання.
                generator_on = True
                battery_pct = base_battery
                battery_est_hours = _GENERATOR_FUEL_HOURS.get(obj.type.value, 8.0)
            else:
                generator_on = False
                battery_pct = base_battery
                battery_est_hours = estimate_backup_hours(
                    obj, base_battery, base_occupancy
                )
            internet_on = obj.has_starlink
            signal = 3 if obj.has_starlink else 1
        elif scenario.type == ScenarioType.SIGNAL_DOWN:
            power_on = last_t.power_on if last_t else True
            generator_on = last_t.generator_on if last_t else False
            battery_pct = base_battery
            battery_est_hours = last_t.battery_est_hours if last_t else 24.0
            internet_on = False
            signal = 0
        elif scenario.type in (ScenarioType.RESET, ScenarioType.NORMAL):
            power_on = True
            generator_on = False
            battery_pct = 100.0
            battery_est_hours = 24.0
            internet_on = True
            signal = 4
            base_temp = 21.0
            base_co2 = max(450.0, base_co2 - 300.0)  # вентиляція запрацювала
            base_humidity = 45.0
            # Людей не «телепортуємо» — вони розходяться поступово (симулятор)
        else:
            continue

        ingest_telemetry(
            db,
            TelemetryCreate(
                object_id=obj.id,
                power_on=power_on,
                battery_pct=round(battery_pct, 1),
                battery_est_hours=round(battery_est_hours, 2),
                temp_c=base_temp,
                humidity_pct=base_humidity,
                co2_ppm=base_co2,
                signal=signal,
                internet_on=internet_on,
                occupancy=base_occupancy,
                generator_on=generator_on,
                scenario_id=scenario.id,
            ),
        )


def start_scenario(db: Session, payload: ScenarioCreate) -> Scenario | None:
    # Завершуємо всі активні сценарії
    db.query(Scenario).filter(Scenario.is_active.is_(True)).update(
        {"is_active": False, "ended_at": datetime.now(timezone.utc)}
    )

    # RESET = деактивація активних сценаріїв + застосування нормальних telemetry,
    # без створення нового активного запису (бо нічого активного не залишається).
    if payload.type == ScenarioType.RESET:
        event = Event(
            type=EventType.SCENARIO_END,
            severity=EventSeverity.INFO,
            message="Сценарій скинуто. Повернення до нормального режиму.",
        )
        db.add(event)
        # Створюємо тимчасовий сценарій для _apply_scenario_immediately, але
        # одразу деактивовуємо — щоб банер "Активний сценарій" зник.
        sc_reset = Scenario(
            type=ScenarioType.RESET,
            scope=payload.scope,
            target=payload.target,
            intensity=payload.intensity,
        )
        db.add(sc_reset)
        db.flush()
        _apply_scenario_immediately(db, sc_reset)
        sc_reset.is_active = False
        sc_reset.ended_at = datetime.now(timezone.utc)
        db.commit()
        return None

    sc = Scenario(
        type=payload.type,
        scope=payload.scope,
        target=payload.target,
        intensity=payload.intensity,
    )
    db.add(sc)
    scenario_type_name = _SCENARIO_TYPE_UA.get(payload.type, payload.type)
    scenario_scope_name = _SCENARIO_SCOPE_UA.get(payload.scope, payload.scope)
    event = Event(
        type=EventType.SCENARIO_START,
        severity=EventSeverity.WARNING
        if payload.type != ScenarioType.NORMAL
        else EventSeverity.INFO,
        message=f"Сценарій {scenario_type_name} розпочато (область={scenario_scope_name}, інтенсивність={payload.intensity})",
    )
    db.add(event)
    db.commit()
    db.refresh(sc)
    _apply_scenario_immediately(db, sc)
    db.commit()
    return sc


SCENARIO_TTL_SECONDS = 600  # 10 хвилин — демо TTL


def get_active_scenario(db: Session) -> Scenario | None:
    # Auto-expire: завершити активні сценарії старші за TTL
    # NOTE: SQLite зберігає tz-naive datetime, тож нормалізуємо до UTC явно
    now = datetime.now(timezone.utc)
    now_naive_utc = now.replace(tzinfo=None)
    threshold_naive = now_naive_utc - timedelta(seconds=SCENARIO_TTL_SECONDS)

    expired_stmt = select(Scenario).where(Scenario.is_active.is_(True))
    for sc in db.scalars(expired_stmt).all():
        if sc.started_at < threshold_naive:
            sc.is_active = False
            sc.ended_at = now
    db.commit()

    stmt = select(Scenario).where(Scenario.is_active.is_(True)).limit(1)
    return db.scalars(stmt).first()


def get_events(db: Session, limit: int = 50) -> list[Event]:
    # Фільтруємо події старші за 24 год — журнал має показувати
    # лише поточну операційну сесію, а не історію за весь час.
    from datetime import datetime, timedelta, timezone

    threshold = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)
    stmt = (
        select(Event).where(Event.ts >= threshold).order_by(desc(Event.ts)).limit(limit)
    )
    return list(db.scalars(stmt))


def get_dashboard_summary(db: Session) -> dict:
    """P1 refactor: aggregate-запит замість N+1 по get_latest_score."""
    objects = get_objects(db)
    total = len(objects)
    counts = {"STABLE": 0, "WARNING": 0, "CRITICAL": 0, "RESCUE_IN_TRANSIT": 0}
    score_sum = 0.0
    scored = 0

    if total > 0:
        object_ids = [obj.id for obj in objects]

        # Aggregate AVG + COUNT GROUP BY status
        last_score_subq = (
            select(
                Score.object_id,
                func.max(Score.ts).label("max_ts"),
            )
            .where(Score.object_id.in_(object_ids))
            .group_by(Score.object_id)
            .subquery()
        )
        rows = list(
            db.execute(
                select(
                    Score.status,
                    func.count(Score.id),
                    func.avg(Score.score),
                )
                .join(
                    last_score_subq,
                    (Score.object_id == last_score_subq.c.object_id)
                    & (Score.ts == last_score_subq.c.max_ts),
                )
                .group_by(Score.status)
            )
        )
        for status_val, count, avg in rows:
            key = status_val.value
            counts[key] = counts.get(key, 0) + int(count)
            if avg is not None:
                score_sum += float(avg) * int(count)
                scored += int(count)

    avg_score = round(score_sum / scored, 1) if scored else 0.0

    active_scenarios = (
        db.scalars(
            select(Scenario).where(Scenario.is_active.is_(True)).limit(1)
        ).first()
        is not None
    )
    active_assignments = len(get_active_assignments(db))
    return {
        "total_objects": total,
        "stable": counts["STABLE"],
        "warning": counts["WARNING"],
        "critical": counts["CRITICAL"],
        "rescue_in_transit": counts["RESCUE_IN_TRANSIT"],
        "avg_city_score": avg_score,
        "active_scenarios": 1 if active_scenarios else 0,
        "active_assignments": active_assignments,
        "ml_model_version": _ml_model_version(),
    }


def _ml_model_version() -> str:
    try:
        from app.ml.inference import model_versions

        return model_versions()["score_model"]
    except Exception:
        return "not_loaded"


def get_public_objects(
    db: Session, lat: float, lon: float, radius_m: int = 2000
) -> list[dict]:
    """Список доступних пунктів для мешканця (public view).

    Використовує batch-запит get_objects_with_state (без N+1), тому
    сторінка мешканця відповідає за мілісекунди, а не 1-2 секунди.
    """
    rows = get_objects_with_state(db)
    out: list[dict] = []
    for row in rows:
        obj = row["object"]
        last_t = row["telemetry"]
        last_s = row["score"]
        if last_t is None:
            continue
        status = last_s.status.value if last_s else "STABLE"
        if status == "CRITICAL":
            continue
        occupancy = last_t.occupancy
        if occupancy >= obj.capacity:
            continue
        dist = _haversine(lat, lon, obj.lat, obj.lon)
        if dist > radius_m:
            continue
        out.append(
            {
                "id": str(obj.id),
                "name": obj.name,
                "type": obj.type.value,
                "lat": obj.lat,
                "lon": obj.lon,
                "address": obj.address,
                "status": status,
                # Для мешканця «є світло» = мережа АБО працюючий генератор
                "power_on": last_t.power_on or last_t.generator_on,
                "internet_on": last_t.internet_on,
                "occupancy": occupancy,
                "capacity": obj.capacity,
                "distance_m": int(dist),
            }
        )
    out.sort(key=lambda x: x["distance_m"])
    return out


def get_operator_briefing(
    db: Session,
    object_id: uuid.UUID,
    use_llm: bool = False,
) -> Optional[dict]:
    """
    Генерує людино-читабельний брифінг для оператора на основі ML score,
    SHAP contributions, anomaly, drift та TTC forecast.

    Args:
        db: SQLAlchemy session
        object_id: ID об'єкта
        use_llm: True → спробувати LLM, False → тільки template (детерміністичний)

    Returns:
        dict з summary, severity, recommended_actions, key_factors, model_confidence, method
        або None якщо об'єкт не знайдено
    """
    from app.ml.operator_briefing import (
        generate_llm_briefing,
        generate_template_briefing,
    )
    from app.ml.features import ScoreFeatures

    obj = db.get(Object, object_id)
    if not obj:
        return None

    score_row = get_latest_score(db, object_id)
    telemetry = get_latest_telemetry(db, object_id)
    if not score_row or not telemetry:
        return None

    components = score_row.components or {}
    ml_confidence = float(components.get("ml_prediction_confidence", 0.85))
    anomaly_score = components.get("anomaly_score")
    anomaly_is_anomaly = bool(components.get("anomaly_is_anomaly", False))

    features = ScoreFeatures(
        battery_pct=float(np.clip(telemetry.battery_pct, 0, 100)),
        battery_est_hours=float(telemetry.battery_est_hours),
        temp_c=float(telemetry.temp_c),
        co2_ppm=float(telemetry.co2_ppm),
        occupancy_ratio=(
            telemetry.occupancy / obj.capacity if obj.capacity > 0 else 0.0
        ),
        criticality=int(obj.criticality),
        has_generator=bool(obj.has_generator),
        has_starlink=bool(obj.has_starlink),
        power_on=bool(telemetry.power_on),
        internet_on=bool(telemetry.internet_on),
        signal=int(telemetry.signal),
        humidity_pct=float(telemetry.humidity_pct),
        generator_on=bool(telemetry.generator_on),
    )

    ttc_minutes = score_row.time_to_critical_min
    drift_detected = components.get("ml_tree_spread", 0) > 8.0

    try:
        if use_llm:
            briefing = generate_llm_briefing(
                object_name=obj.name,
                object_type=obj.type.value,
                features=features,
                ml_score=score_row.score,
                ml_status=score_row.status.value,
                ml_confidence=ml_confidence,
                anomaly_detected=anomaly_is_anomaly,
                drift_detected=drift_detected,
                ttc_minutes=ttc_minutes,
            )
        else:
            briefing = generate_template_briefing(
                object_name=obj.name,
                object_type=obj.type.value,
                features=features,
                ml_score=score_row.score,
                ml_status=score_row.status.value,
                ml_confidence=ml_confidence,
                anomaly_detected=anomaly_is_anomaly,
                drift_detected=drift_detected,
                ttc_minutes=ttc_minutes,
            )
    except Exception as e:
        logger.exception("Briefing generation failed: %s", e)
        return None

    return {
        "summary": briefing.summary,
        "severity": briefing.severity,
        "recommended_actions": list(briefing.recommended_actions),
        "key_factors": [
            {"feature": k, "contribution": v} for k, v in briefing.key_factors
        ],
        "model_confidence": briefing.model_confidence,
        "method": briefing.method,
        "object_id": str(obj.id),
        "object_name": obj.name,
        "object_type": obj.type.value,
        "ml_score": score_row.score,
        "ml_status": score_row.status.value,
        "ttc_minutes": ttc_minutes,
        "anomaly_detected": anomaly_is_anomaly,
        "anomaly_score": float(anomaly_score) if anomaly_score is not None else None,
        "drift_detected": drift_detected,
    }


def get_drift_status() -> dict:
    """
    Поточний стан drift detection:
    - чи є reference dataset
    - скільки observations зібрано
    - чи є drift в поточному вікні
    - per-feature drift scores
    """
    try:
        from app.ml.monitoring.drift import get_drift_detector

        detector = get_drift_detector()
        report = detector.check_drift()
        return {
            "n_observations": len(detector._current),
            "has_reference": detector._reference is not None,
            "drift_detected": bool(report.drift_detected) if report else False,
            "n_drifted_features": int(report.n_drifted) if report else 0,
            "features": [
                {
                    "feature": f.feature,
                    "statistic": round(float(f.statistic), 4),
                    "p_value": round(float(f.p_value), 4),
                    "drifted": bool(f.drifted),
                    "current_mean": round(float(f.current_mean), 3),
                    "reference_mean": round(float(f.reference_mean), 3),
                }
                for f in (report.feature_drifts if report else [])
            ],
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.exception("Drift check failed: %s", e)
        return {
            "n_observations": 0,
            "has_reference": False,
            "drift_detected": False,
            "n_drifted_features": 0,
            "features": [],
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "error": str(e),
        }


def get_model_cards() -> list[dict]:
    """
    Повертає список model cards для governance dashboard.

    Кожна картка містить: model_name, model_version, model_type,
    intended_use, training_data, features, target, metrics,
    limitations, ethical_considerations, owner, contact.
    """
    from app.ml.model_cards import MODEL_CARDS, list_model_cards

    result: list[dict] = []
    for name in list_model_cards():
        card = MODEL_CARDS[name]
        result.append(card.to_dict())
    return result


def get_model_health() -> dict:
    """
    Повертає health ML pipeline:
    - чи завантажені моделі
    - online learner state
    - drift detector state
    - last training timestamp
    """
    from app.ml.inference import model_versions
    from app.ml.online_learning import get_online_scorer

    online = get_online_scorer()
    online_health = online.health_check()

    artifacts_dir_status: dict = {}
    try:
        meta_path = (
            Path(__file__).parent / "ml" / "artifacts" / "score_model_1.0.0.meta.json"
        )
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            artifacts_dir_status["score_model"] = {
                "trained_at": meta.get("trained_at"),
                "n_samples": meta.get("n_samples"),
                "metrics": meta.get("metrics", {}),
            }
        ranker_path = (
            Path(__file__).parent / "ml" / "artifacts" / "ranker_model_1.0.0.meta.json"
        )
        if ranker_path.exists():
            meta = json.loads(ranker_path.read_text())
            artifacts_dir_status["ranker_model"] = {
                "trained_at": meta.get("trained_at"),
                "metrics": meta.get("metrics", {}),
            }
    except Exception as e:
        artifacts_dir_status["error"] = str(e)

    return {
        "models": model_versions(),
        "online_learner": online_health,
        "artifacts": artifacts_dir_status,
    }


def run_counterfactual_for_object(
    db: Session,
    object_id: uuid.UUID,
    intervention_type: str = "generator",
    eta_min: int = 30,
) -> Optional[dict]:
    """
    Counterfactual "що якщо": обчислює, як зміниться ML score
    конкретного об'єкта якщо застосувати intervention
    (наприклад, призначити генератор).

    Args:
        db: SQLAlchemy session
        object_id: ID об'єкта
        intervention_type: тип втручання (generator/tech_team/starlink/fuel/evacuation)
        eta_min: ETA в хвилинах

    Returns:
        dict з before/after scores, status, TTC, SHAP delta, recommendation
        або None якщо об'єкт не знайдено
    """
    from app.ml.counterfactual import (
        InterventionSpec,
        analyze_intervention,
    )
    from app.ml.features import ScoreFeatures

    obj = db.get(Object, object_id)
    if not obj:
        return None

    score_row = get_latest_score(db, object_id)
    telemetry = get_latest_telemetry(db, object_id)
    if not score_row or not telemetry:
        return None

    base_features = ScoreFeatures(
        battery_pct=float(np.clip(telemetry.battery_pct, 0, 100)),
        battery_est_hours=float(telemetry.battery_est_hours),
        temp_c=float(telemetry.temp_c),
        co2_ppm=float(telemetry.co2_ppm),
        occupancy_ratio=(
            telemetry.occupancy / obj.capacity if obj.capacity > 0 else 0.0
        ),
        criticality=int(obj.criticality),
        has_generator=bool(obj.has_generator),
        has_starlink=bool(obj.has_starlink),
        power_on=bool(telemetry.power_on),
        internet_on=bool(telemetry.internet_on),
        signal=int(telemetry.signal),
        humidity_pct=float(telemetry.humidity_pct),
        generator_on=bool(telemetry.generator_on),
    )

    intervention = InterventionSpec(
        object_id=str(object_id),
        intervention_type=intervention_type,
        eta_min=eta_min,
    )

    try:
        result = analyze_intervention(obj.name, base_features, intervention)
    except Exception as e:
        logger.exception("Counterfactual failed: %s", e)
        return None

    # Compute baseline SHAP для порівняння
    from app.ml.explain import explain_score

    before_shap = explain_score(base_features)
    # After features
    from app.ml.counterfactual import _apply_intervention_to_features

    after_features = _apply_intervention_to_features(base_features, intervention)
    after_shap = explain_score(after_features)

    # Top deltas (які фіч найбільше змінилися)
    feature_deltas: list[dict] = []
    for fname in before_shap:
        b = before_shap.get(fname, 0.0)
        a = after_shap.get(fname, 0.0)
        delta = a - b
        if abs(delta) > 0.01:
            feature_deltas.append(
                {
                    "feature": fname,
                    "before": round(b, 3),
                    "after": round(a, 3),
                    "delta": round(delta, 3),
                }
            )
    feature_deltas.sort(key=lambda d: -abs(d["delta"]))

    intervention_ua = {
        "generator": "Генератор",
        "tech_team": "Техбригада",
        "starlink": "Starlink",
        "fuel": "Паливо",
        "evacuation": "Евакуація",
    }.get(intervention_type, intervention_type)

    return {
        "object_id": str(obj.id),
        "object_name": obj.name,
        "object_type": obj.type.value,
        "intervention_type": intervention_type,
        "intervention_label": intervention_ua,
        "eta_min": eta_min,
        "before": {
            "score": result.before_score,
            "status": result.before_status,
            "ttc_min": result.before_ttc_min,
        },
        "after": {
            "score": result.after_score,
            "status": result.after_status,
            "ttc_min": result.after_ttc_min,
        },
        "score_delta": result.score_delta,
        "ttc_delta_min": result.ttc_delta_min,
        "will_rescue": result.will_rescue,
        "top_feature_changes": feature_deltas[:5],
        "recommendation": (
            f"Якщо призначити {intervention_ua} — score зміниться на {result.score_delta:+.1f} "
            f"({result.before_status} → {result.after_status})."
        ),
    }


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Відстань у метрах між двома точками."""
    from math import asin, cos, pi, sin, sqrt

    r = 6371000.0
    p = pi / 180
    a = (
        sin((lat2 - lat1) * p / 2) ** 2
        + cos(lat1 * p) * cos(lat2 * p) * sin((lon2 - lon1) * p / 2) ** 2
    )
    return 2 * r * asin(sqrt(a))
