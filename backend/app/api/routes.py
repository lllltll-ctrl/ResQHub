"""
REST API endpoints для ResQHub.

Маршрути:
  GET    /api/objects
  POST   /api/objects
  GET    /api/objects/{id}
  POST   /api/telemetry
  GET    /api/telemetry/{object_id}
  GET    /api/scores/{object_id}
  GET    /api/dashboard
  GET    /api/routing
  POST   /api/assignments
  GET    /api/assignments
  POST   /api/scenarios
  GET    /api/scenarios/active
  GET    /api/events
  GET    /api/public/objects
  WS     /ws/stream
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncGenerator


# Глобальний event loop, що використовується broadcast_event_loop.
# Зберігається при першому запуску додатку, щоб sync-роути могли
# пушити повідомлення через run_coroutine_threadsafe.
_main_event_loop: asyncio.AbstractEventLoop | None = None


def set_main_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _main_event_loop
    _main_event_loop = loop


from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas import (
    AssignmentCreate,
    AssignmentOut,
    DashboardSummary,
    EventOut,
    ObjectCreate,
    ObjectOut,
    PublicObjectOut,
    RoutingRecommendation,
    ScenarioCreate,
    ScenarioOut,
    TelemetryCreate,
    TelemetryOut,
    _to_utc_iso,
)
from app.services import orchestrator

router = APIRouter(prefix="/api")
public_router = APIRouter(prefix="/public")


def _assignment_event_payload(a) -> dict:
    """Серіалізує Assignment для WS broadcast."""
    return {
        "id": str(a.id),
        "object_id": str(a.object_id),
        "resource_type": a.resource_type.value
        if hasattr(a.resource_type, "value")
        else str(a.resource_type),
        "status": a.status.value if hasattr(a.status, "value") else str(a.status),
        "eta_min": a.eta_min,
        "created_at": _to_utc_iso(a.created_at) if a.created_at else None,
        "arrived_at": _to_utc_iso(a.arrived_at) if a.arrived_at else None,
    }


def _scenario_event_payload(s) -> dict | None:
    """Серіалізує Scenario для WS broadcast. None → null."""
    if s is None:
        return None
    return {
        "id": str(s.id),
        "type": s.type.value if hasattr(s.type, "value") else str(s.type),
        "scope": s.scope.value if hasattr(s.scope, "value") else str(s.scope),
        "target": s.target,
        "intensity": s.intensity,
        "started_at": _to_utc_iso(s.started_at) if s.started_at else None,
        "ended_at": _to_utc_iso(s.ended_at) if s.ended_at else None,
        "is_active": s.is_active,
    }


def _schedule_broadcast(message: dict) -> None:
    """Планує WS-broadcast із sync-роуту. Використовує збережений main loop,
    бо sync-роут виконується в threadpool без asyncio loop."""
    if _main_event_loop is None:
        return
    asyncio.run_coroutine_threadsafe(manager.broadcast(message), _main_event_loop)


# ---------- Objects ----------
@router.get("/objects", response_model=list[ObjectOut])
def list_objects(db: Session = Depends(get_db), district: str | None = None):
    return orchestrator.get_objects(db, district=district)


@router.post("/objects", response_model=ObjectOut, status_code=status.HTTP_201_CREATED)
def post_object(payload: ObjectCreate, db: Session = Depends(get_db)):
    return orchestrator.create_object(db, payload)


@router.get("/objects/{oid}", response_model=ObjectOut)
def get_object(oid: uuid.UUID, db: Session = Depends(get_db)):
    obj = orchestrator.get_object(db, oid)
    if obj is None:
        raise HTTPException(404, "Object not found")
    return obj


# ---------- Telemetry ----------
@router.post(
    "/telemetry", response_model=TelemetryOut, status_code=status.HTTP_201_CREATED
)
def post_telemetry(payload: TelemetryCreate, db: Session = Depends(get_db)):
    try:
        return orchestrator.ingest_telemetry(db, payload)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/telemetry/{object_id}", response_model=list[TelemetryOut])
def list_telemetry(
    object_id: uuid.UUID, db: Session = Depends(get_db), limit: int = 50
):
    from sqlalchemy import desc, select
    from app.models.domain import Telemetry

    stmt = (
        select(Telemetry)
        .where(Telemetry.object_id == object_id)
        .order_by(desc(Telemetry.ts))
        .limit(limit)
    )
    return list(db.scalars(stmt))[::-1]


# ---------- Scores ----------
@router.get("/scores/{object_id}")
def list_scores(object_id: uuid.UUID, db: Session = Depends(get_db), limit: int = 50):
    from sqlalchemy import desc, select
    from app.models.domain import Score

    stmt = (
        select(Score)
        .where(Score.object_id == object_id)
        .order_by(desc(Score.ts))
        .limit(limit)
    )
    rows = list(db.scalars(stmt))[::-1]
    return [
        {
            "id": str(r.id),
            "object_id": str(r.object_id),
            "ts": _to_utc_iso(r.ts),
            "score": r.score,
            "status": r.status.value,
            "time_to_critical_min": r.time_to_critical_min,
            "components": r.components,
        }
        for r in rows
    ]


# ---------- Dashboard ----------
@router.get("/dashboard", response_model=DashboardSummary)
def dashboard(db: Session = Depends(get_db)):
    return orchestrator.get_dashboard_summary(db)


@router.get("/dashboard/full")
def dashboard_full(db: Session = Depends(get_db)):
    """Об'єкти + остання телеметрія + score одним запитом (для карти)."""
    rows = orchestrator.get_objects_with_state(db)
    out = []
    for row in rows:
        obj = row["object"]
        t = row["telemetry"]
        s = row["score"]
        out.append(
            {
                "id": str(obj.id),
                "name": obj.name,
                "type": obj.type.value,
                "lat": obj.lat,
                "lon": obj.lon,
                "district": obj.district,
                "address": obj.address,
                "criticality": obj.criticality,
                "capacity": obj.capacity,
                "has_generator": obj.has_generator,
                "has_starlink": obj.has_starlink,
                "telemetry": (
                    {
                        "power_on": t.power_on,
                        "battery_pct": t.battery_pct,
                        "battery_est_hours": t.battery_est_hours,
                        "temp_c": t.temp_c,
                        "humidity_pct": t.humidity_pct,
                        "co2_ppm": t.co2_ppm,
                        "signal": t.signal,
                        "internet_on": t.internet_on,
                        "occupancy": t.occupancy,
                        "generator_on": t.generator_on,
                        "ts": _to_utc_iso(t.ts),
                    }
                    if t
                    else None
                ),
                "score": (
                    {
                        "score": s.score,
                        "status": s.status.value,
                        "time_to_critical_min": s.time_to_critical_min,
                        "components": s.components,
                        "ts": _to_utc_iso(s.ts),
                    }
                    if s
                    else None
                ),
            }
        )
    return out


# ---------- Routing ----------
@router.get("/routing", response_model=list[RoutingRecommendation])
def routing(db: Session = Depends(get_db), limit: int = 5):
    return orchestrator.get_routing_recommendations(db, limit=limit)


# ---------- Counterfactual (What-if) ----------
@router.get("/counterfactual/{object_id}")
def counterfactual(
    object_id: uuid.UUID,
    intervention: str = "generator",
    eta_min: int = 30,
    db: Session = Depends(get_db),
):
    """What-if: як зміниться ML-score об'єкта, якщо направити ресурс ЗАРАЗ.

    intervention: generator | fuel | starlink | tech_team | evacuation.
    Повертає before/after score+status+ttc, топ-зміни фіч (SHAP delta)
    і людино-читабельну рекомендацію. Дозволяє оператору побачити ефект
    ДО відправки техніки.
    """
    result = orchestrator.run_counterfactual_for_object(
        db, object_id, intervention_type=intervention, eta_min=eta_min
    )
    if result is None:
        raise HTTPException(404, "Object not found or no telemetry")
    return result


# ---------- Assignments ----------
@router.post(
    "/assignments", response_model=AssignmentOut, status_code=status.HTTP_201_CREATED
)
def post_assignment(payload: AssignmentCreate, db: Session = Depends(get_db)):
    try:
        a = orchestrator.create_assignment(db, payload)
        # Миттєвий broadcast — UI не має чекати 3с
        _schedule_broadcast(_assignment_event_payload(a))
        return a
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/assignments", response_model=list[AssignmentOut])
def list_assignments(db: Session = Depends(get_db)):
    return orchestrator.get_active_assignments(db)


@router.post("/assignments/{assignment_id}/complete", response_model=AssignmentOut)
def complete_assignment(
    assignment_id: uuid.UUID,
    outcome: str = "success",
    db: Session = Depends(get_db),
):
    """Завершує призначення: повертає об'єкт у нормальний режим.

    Викликається з UI після того, як машина "приїхала" на об'єкт (після eta_min).
    Застосовує ефект ресурсу до telemetry та генерує подію прибуття.
    """
    if outcome not in {"success", "cancelled"}:
        raise HTTPException(400, "outcome must be 'success' or 'cancelled'")
    a = orchestrator.complete_assignment(db, assignment_id, outcome=outcome)
    if a is None:
        raise HTTPException(404, "Assignment not found")
    _schedule_broadcast(_assignment_event_payload(a))
    return a


# ---------- Scenarios ----------
@router.post(
    "/scenarios", response_model=ScenarioOut | None, status_code=status.HTTP_201_CREATED
)
def post_scenario(payload: ScenarioCreate, db: Session = Depends(get_db)):
    sc = orchestrator.start_scenario(db, payload)
    # Миттєвий broadcast — UI не чекає наступного 3с snapshot.
    try:
        from app.services.orchestrator import get_active_scenario

        active = get_active_scenario(db) if sc is not None else None
    except Exception:
        active = sc
    _schedule_broadcast(
        {"type": "scenario_change", "scenario": _scenario_event_payload(active)}
    )
    return sc


@router.get("/scenarios/active", response_model=ScenarioOut | None)
def active_scenario(db: Session = Depends(get_db)):
    return orchestrator.get_active_scenario(db)


# ---------- Events ----------
@router.get("/events", response_model=list[EventOut])
def list_events(db: Session = Depends(get_db), limit: int = 50):
    return orchestrator.get_events(db, limit=limit)


# ---------- Operator Briefing (ML/LLM) ----------
@router.get("/briefing/{object_id}")
def get_briefing(
    object_id: uuid.UUID,
    db: Session = Depends(get_db),
    use_llm: bool = False,
):
    """
    Генерує людино-читабельний брифінг для оператора.

    Args:
        object_id: UUID об'єкта
        use_llm: true → спробувати LLM (потребує OPENAI_API_KEY),
                 false → тільки template (детерміністичний, завжди працює)

    Returns:
        dict з summary, recommended_actions, key_factors, model_confidence, method
    """
    briefing = orchestrator.get_operator_briefing(db, object_id, use_llm=use_llm)
    if briefing is None:
        raise HTTPException(
            status_code=404,
            detail="Object not found or no recent score/telemetry",
        )
    return briefing


# ---------- Counterfactual "what-if" ----------
@router.post("/counterfactual/{object_id}")
def post_counterfactual(
    object_id: uuid.UUID,
    intervention_type: str = "generator",
    eta_min: int = 30,
    db: Session = Depends(get_db),
):
    """
    Counterfactual analysis: "що якщо призначити ресурс X об'єкту Y?".

    Args:
        object_id: UUID об'єкта
        intervention_type: generator | tech_team | starlink | fuel | evacuation
        eta_min: ETA в хвилинах (впливає на прогноз)

    Returns:
        dict з before/after scores, status, TTC, top SHAP deltas
    """
    valid_types = {"generator", "tech_team", "starlink", "fuel", "evacuation"}
    if intervention_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid intervention_type. Must be one of: {sorted(valid_types)}",
        )

    result = orchestrator.run_counterfactual_for_object(
        db, object_id, intervention_type=intervention_type, eta_min=eta_min
    )
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Object not found or no recent score/telemetry",
        )
    return result


# ---------- Model Cards & Health (ML Governance) ----------
@router.get("/models/cards")
def get_model_cards():
    """
    Повертає список model cards для ML governance dashboard.
    Включає: intended use, training data, features, metrics,
    limitations, ethical considerations для кожної моделі.
    """
    return orchestrator.get_model_cards()


@router.get("/models/health")
def get_model_health():
    """
    Повертає health ML pipeline: model versions, online learner state,
    drift detector state, останні training timestamps.
    """
    return orchestrator.get_model_health()


@router.get("/ml/drift")
def get_drift_status():
    """
    Поточний стан concept drift detection:
    - n_observations зібрано
    - drift_detected flag
    - per-feature KS-test scores
    """
    return orchestrator.get_drift_status()


# ---------- Public (мешканський UI) ----------
@public_router.get("/objects", response_model=list[PublicObjectOut])
def public_objects(
    db: Session = Depends(get_db),
    lat: float = 50.2647,
    lon: float = 28.6647,
    radius_m: int = 2000,
):
    return orchestrator.get_public_objects(db, lat=lat, lon=lon, radius_m=radius_m)


# ---------- WebSocket ----------
class ConnectionManager:
    """Менеджер активних WS-з'єднань для push-realtime_PUSH-оновлень."""

    def __init__(self) -> None:
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, message: dict) -> None:
        text = json.dumps(message, default=str)
        stale: list[WebSocket] = []
        for ws in self.active:
            try:
                await ws.send_text(text)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.disconnect(ws)


manager = ConnectionManager()


@router.websocket("/ws/stream")
async def ws_stream(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        while True:
            # Сервер залишається активним; клієнт може надсилати ping
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        manager.disconnect(websocket)


async def broadcast_event_loop() -> AsyncGenerator[None, None]:
    """Фоново шле клієнтам snapshot стану системи кожні 3 секунди.
    Паралельно пушить нові події (type=event) для оперативного журналу.
    """
    from datetime import datetime, timezone

    from app.core.database import SessionLocal

    # Пушимо лише події, що виникли ПІСЛЯ старту loop → оперативний журнал
    # у клієнта починається порожнім, а не з бэклогу. Відстежуємо за ts
    # (а не за UUID — uuid4 не впорядкований, тож рядкове порівняння id
    # пропускало/дублювало події). SQLite зберігає naive-UTC.
    last_event_ts = datetime.now(timezone.utc).replace(tzinfo=None)
    while True:
        await asyncio.sleep(3)
        db = SessionLocal()
        try:
            # Серверне автозавершення доставок — виконуємо ЗАВЖДИ, навіть коли
            # немає жодного активного WS-клієнта. Інакше доставки «зависали» б
            # у статусі RESCUE_IN_TRANSIT, поки хтось не відкриє вкладку.
            orchestrator.auto_complete_due_assignments(db)
            # Далі — лише якщо є кому слати snapshot (економимо CPU).
            if not manager.active:
                continue
            summary = orchestrator.get_dashboard_summary(db)
            objects_state = orchestrator.get_objects_with_state(db)
            active_assignments = orchestrator.get_active_assignments(db)
            snapshot = {
                "type": "snapshot",
                "summary": summary,
                "assignments": [
                    _assignment_event_payload(a) for a in active_assignments
                ],
                "objects": [
                    {
                        "id": str(row["object"].id),
                        "name": row["object"].name,
                        "status": row["score"].status.value
                        if row["score"]
                        else "STABLE",
                        "score": row["score"].score if row["score"] else None,
                        "battery_pct": row["telemetry"].battery_pct
                        if row["telemetry"]
                        else None,
                        "power_on": row["telemetry"].power_on
                        if row["telemetry"]
                        else None,
                        "occupancy": row["telemetry"].occupancy
                        if row["telemetry"]
                        else 0,
                        "ts": (
                            _to_utc_iso(row["telemetry"].ts)
                            if row["telemetry"]
                            else None
                        ),
                    }
                    for row in objects_state
                ],
            }
            await manager.broadcast(snapshot)

            # Push нових подій з моменту останнього broadcast (за ts)
            recent_events = orchestrator.get_events(db, limit=20)
            if recent_events:
                new_events = [ev for ev in recent_events if ev.ts > last_event_ts]
                if new_events:
                    last_event_ts = max(ev.ts for ev in new_events)
                    # reversed → від найстарішої до найновішої
                    for ev in reversed(new_events):
                        await manager.broadcast(
                            {
                                "type": "event",
                                "event": {
                                    "id": str(ev.id),
                                    "ts": _to_utc_iso(ev.ts),
                                    "object_id": str(ev.object_id)
                                    if ev.object_id
                                    else None,
                                    "scenario_id": str(ev.scenario_id)
                                    if ev.scenario_id
                                    else None,
                                    "type": ev.type.value,
                                    "message": ev.message,
                                    "severity": ev.severity.value,
                                },
                            }
                        )
        finally:
            db.close()


router.include_router(public_router)
