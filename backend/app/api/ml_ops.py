"""
ML operations API endpoints:
  - GET  /api/ml/health         — стан усіх моделей
  - GET  /api/ml/drift          — останній drift report
  - GET  /api/ml/drift/check    — перевірити drift зараз
  - GET  /api/ml/anomalies      — останні anomalies
  - GET  /api/ml/anomalies/recent — recent rolling window
  - POST /api/ml/retrain        — перетренувати модель
  - GET  /api/ml/versions       — поточні активні версії + A/B traffic split
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from app.ml.inference import model_versions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ml", tags=["ml-ops"])


# ─────────────────────────────────────────────────────────────────────
# A/B test registry
# ─────────────────────────────────────────────────────────────────────
class ABConfig(BaseModel):
    """Конфігурація A/B тесту."""

    model_config = {"protected_namespaces": ()}

    enabled: bool = False
    model_a_version: str
    model_b_version: str
    traffic_split: float = Field(default=0.5, ge=0.0, le=1.0)
    started_at: Optional[str] = None


_ab_config: Optional[ABConfig] = None
_ab_lock = threading.Lock()


def get_active_model_version() -> str:
    """Повертає версію моделі для поточного запиту (з урахуванням A/B)."""
    with _ab_lock:
        if _ab_config is not None and _ab_config.enabled:
            import random

            if random.random() < _ab_config.traffic_split:
                return _ab_config.model_a_version
            return _ab_config.model_b_version
    versions = model_versions()
    return versions["score_model"]


@router.get("/health")
def ml_health() -> dict[str, Any]:
    """Стан усіх ML-моделей."""
    from app.ml.monitoring.anomaly import get_anomaly_detector
    from app.ml.monitoring.drift import get_drift_detector

    try:
        drift_detector = get_drift_detector()
        drift_status = {
            "reference_loaded": drift_detector._reference is not None,
            "window_size": len(drift_detector._current),
        }
    except Exception as e:
        drift_status = {"error": str(e)}

    try:
        anomaly_detector = get_anomaly_detector()
        anomaly_status = anomaly_detector.health_check()
    except Exception as e:
        anomaly_status = {"error": str(e)}

    return {
        "status": "ok",
        "models": model_versions(),
        "drift": drift_status,
        "anomaly": anomaly_status,
        "ab_test": _ab_config.model_dump() if _ab_config else None,
    }


@router.get("/drift")
def drift_report() -> dict[str, Any]:
    """Повертає останній збережений drift report."""
    from app.ml.monitoring.drift import DRIFT_REPORT_PATH

    if not DRIFT_REPORT_PATH.exists():
        return {"status": "no_report", "message": "Run /api/ml/drift/check first"}
    return json.loads(DRIFT_REPORT_PATH.read_text())


@router.get("/drift/check")
def drift_check_now() -> dict[str, Any]:
    """Запускає drift check зараз."""
    from app.ml.monitoring.drift import get_drift_detector

    try:
        detector = get_drift_detector()
        if detector._reference is None:
            raise HTTPException(503, "Drift detector not initialized (no reference)")
        report = detector.check_drift()
        return report.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Drift check failed: {e}")


@router.post("/drift/observe")
def drift_observe(features: list[float]) -> dict[str, Any]:
    """Додає один observation у drift detector (для симулятора)."""
    from app.ml.monitoring.drift import get_drift_detector

    detector = get_drift_detector()
    detector.observe(features)
    return {"window_size": len(detector._current)}


@router.get("/anomalies")
def anomalies_list(limit: int = 50) -> dict[str, Any]:
    """Повертає останні anomalies."""
    from app.ml.monitoring.anomaly import get_anomaly_detector

    detector = get_anomaly_detector()
    recent = detector.recent_anomalies(limit=limit)
    return {
        "n_anomalies": len(recent),
        "anomalies": [
            {
                "object_id": a.object_id,
                "timestamp": a.timestamp,
                "score": a.score,
                "is_anomaly": a.is_anomaly,
                "top_features": a.top_anomalous_features,
                "reason": a.reason,
            }
            for a in recent
        ],
    }


@router.post("/anomalies/score")
def anomaly_score(payload: dict[str, Any]) -> dict[str, Any]:
    """Оцінює один telemetry reading."""
    from app.ml.monitoring.anomaly import get_anomaly_detector

    object_id = payload.get("object_id", "unknown")
    features = payload.get("features", [])
    if len(features) != 13:
        raise HTTPException(400, "Expected 13 features")
    detector = get_anomaly_detector()
    score = detector.score(object_id, features)
    return {
        "object_id": score.object_id,
        "is_anomaly": score.is_anomaly,
        "score": score.score,
        "top_features": score.top_anomalous_features,
        "reason": score.reason,
    }


class RetrainRequest(BaseModel):
    n_samples: int = Field(default=8000, ge=1000, le=50000)
    async_run: bool = True


@router.post("/retrain")
def ml_retrain(req: RetrainRequest, background: BackgroundTasks) -> dict[str, Any]:
    """Перетренувати score + ranker моделі.

    За замовчуванням async (background task) — повертає job_id.
    """
    job_id = str(uuid.uuid4())

    def _train() -> None:
        from app.ml import train as train_mod

        try:
            logger.info("Retrain job %s started", job_id)
            # Re-use training logic з модифікованим n_samples
            train_mod.N_SAMPLES = req.n_samples
            train_mod.main()
            logger.info("Retrain job %s completed", job_id)
        except Exception as e:
            logger.exception("Retrain job %s failed: %s", job_id, e)

    if req.async_run:
        background.add_task(_train)
        return {
            "status": "scheduled",
            "job_id": job_id,
            "n_samples": req.n_samples,
        }
    else:
        _train()
        return {
            "status": "completed",
            "job_id": job_id,
            "n_samples": req.n_samples,
        }


@router.get("/versions")
def ml_versions() -> dict[str, Any]:
    """Поточні версії моделей + A/B config."""
    return {
        "active_versions": model_versions(),
        "ab_test": _ab_config.model_dump() if _ab_config else None,
    }


@router.post("/ab/start")
def ab_start(config: ABConfig) -> dict[str, Any]:
    """Запустити A/B тест між двома версіями моделі."""
    global _ab_config
    with _ab_lock:
        _ab_config = ABConfig(
            enabled=True,
            model_a_version=config.model_a_version,
            model_b_version=config.model_b_version,
            traffic_split=config.traffic_split,
            started_at=datetime.utcnow().isoformat(),
        )
    return {"status": "started", "config": _ab_config.model_dump()}


@router.post("/ab/stop")
def ab_stop() -> dict[str, Any]:
    """Зупинити A/B тест."""
    global _ab_config
    with _ab_lock:
        _ab_config = None
    return {"status": "stopped"}
