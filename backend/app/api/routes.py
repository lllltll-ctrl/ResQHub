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
)
from app.services import orchestrator

router = APIRouter(prefix="/api")
public_router = APIRouter(prefix="/public")


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
            "ts": r.ts.isoformat(),
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
                        "ts": t.ts.isoformat(),
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
                        "ts": s.ts.isoformat(),
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


# ---------- Assignments ----------
@router.post(
    "/assignments", response_model=AssignmentOut, status_code=status.HTTP_201_CREATED
)
def post_assignment(payload: AssignmentCreate, db: Session = Depends(get_db)):
    try:
        return orchestrator.create_assignment(db, payload)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/assignments", response_model=list[AssignmentOut])
def list_assignments(db: Session = Depends(get_db)):
    return orchestrator.get_active_assignments(db)


# ---------- Scenarios ----------
@router.post(
    "/scenarios", response_model=ScenarioOut | None, status_code=status.HTTP_201_CREATED
)
def post_scenario(payload: ScenarioCreate, db: Session = Depends(get_db)):
    return orchestrator.start_scenario(db, payload)


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
    from app.core.database import SessionLocal

    last_event_id_seen: str | None = None
    while True:
        await asyncio.sleep(3)
        if not manager.active:
            continue
        db = SessionLocal()
        try:
            summary = orchestrator.get_dashboard_summary(db)
            objects_state = orchestrator.get_objects_with_state(db)
            snapshot = {
                "type": "snapshot",
                "summary": summary,
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
                            row["telemetry"].ts.isoformat()
                            if row["telemetry"]
                            else None
                        ),
                    }
                    for row in objects_state
                ],
            }
            await manager.broadcast(snapshot)

            # Push нових подій з моменту останнього broadcast
            recent_events = orchestrator.get_events(db, limit=10)
            if recent_events:
                # Визначаємо "нові" — ті, чий id більший за last_event_id_seen
                new_events: list[EventOut] = []
                for ev in recent_events:
                    if last_event_id_seen is None or str(ev.id) > last_event_id_seen:
                        new_events.append(ev)
                if new_events:
                    last_event_id_seen = str(recent_events[0].id)
                    for ev in reversed(new_events):
                        await manager.broadcast(
                            {
                                "type": "event",
                                "event": {
                                    "id": str(ev.id),
                                    "ts": ev.ts.isoformat(),
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
