"""
FastAPI entry point для ResQHub backend.

Запуск:
    uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.ml_ops import router as ml_ops_router
from app.api.routes import broadcast_event_loop, router, set_main_event_loop
from app.core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio

    # Зберігаємо main event loop, щоб sync-роути могли пушити WS-повідомлення
    # через run_coroutine_threadsafe.
    set_main_event_loop(asyncio.get_running_loop())
    task = asyncio.create_task(broadcast_event_loop())
    yield
    task.cancel()


app = FastAPI(
    title="ResQHub API",
    description="Міська платформа моніторингу енергостійкості критичних об'єктів",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(ml_ops_router)


@app.get("/")
def root():
    return {
        "name": "ResQHub",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": {
            "objects": "/api/objects",
            "telemetry": "/api/telemetry",
            "scores": "/api/scores/{object_id}",
            "dashboard": "/api/dashboard",
            "routing": "/api/routing",
            "assignments": "/api/assignments",
            "scenarios": "/api/scenarios",
            "events": "/api/events",
            "public": "/api/public/objects",
            "ws": "/api/ws/stream",
            "ml_health": "/api/ml/health",
            "ml_drift": "/api/ml/drift",
            "ml_anomalies": "/api/ml/anomalies",
            "ml_retrain": "/api/ml/retrain",
            "ml_ab": "/api/ml/ab",
        },
    }


@app.get("/health")
def health():
    return {"status": "ok"}
