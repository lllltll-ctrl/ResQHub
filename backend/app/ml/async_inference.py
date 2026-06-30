"""
Async ML inference через ARQ (Async Redis Queue).

Архітектура:
  - HTTP POST /api/telemetry → одразу повертає 202 Accepted з job_id
  - Background worker (ARQ) обробляє: ML inference + anomaly + drift observe
  - WebSocket пушить оновлення клієнтам через broadcast
  - Результат зберігається в БД синхронно

Якщо Redis недоступний — fallback на синхронний режим (background thread).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class AsyncMLConfig:
    """Конфігурація async ML worker."""

    redis_url: str
    queue_name: str = "resqhub_ml"
    max_jobs: int = 8
    job_timeout_sec: int = 30
    enabled: bool = True

    @classmethod
    def from_env(cls) -> "AsyncMLConfig":
        return cls(
            redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            queue_name=os.getenv("ARQ_QUEUE_NAME", "resqhub_ml"),
            max_jobs=int(os.getenv("ARQ_MAX_JOBS", "8")),
            job_timeout_sec=int(os.getenv("ARQ_JOB_TIMEOUT", "30")),
            enabled=os.getenv("ASYNC_ML_ENABLED", "false").lower() == "true",
        )


CONFIG = AsyncMLConfig.from_env()


# ─────────────────────────────────────────────────────────────────────
# Job payloads
# ─────────────────────────────────────────────────────────────────────
@dataclass
class TelemetryProcessingJob:
    """Job для async обробки telemetry."""

    job_id: str
    telemetry_id: str
    object_id: str
    enqueued_at: float


# ─────────────────────────────────────────────────────────────────────
# Worker functions
# ─────────────────────────────────────────────────────────────────────
async def process_telemetry_job(
    ctx: dict[str, Any], job_data: dict[str, Any]
) -> dict[str, Any]:
    """
    ARQ worker function — обробляє один telemetry record.

    Кроки:
      1. Завантажує Telemetry + Object з БД
      2. Запускає ML inference (score + status)
      3. Запускає anomaly detection
      4. Оновлює drift detector
      5. Зберігає Score в БД
      6. Broadcast через WebSocket
    """
    import time

    job_id = job_data.get("job_id", "unknown")
    start = time.time()
    logger.info("ARQ job %s started", job_id)

    try:
        # Цей код виконується в worker process
        # Уникаємо circular imports — імпортуємо тут
        from app.services.orchestrator import _build_features_from_telemetry
        from app.ml.inference import predict_score
        from app.ml.monitoring.anomaly import get_anomaly_detector
        from app.ml.monitoring.drift import get_drift_detector
        from app.ml.features import ScoreFeatures
        from app.ml.explain import explain_score
        from app.services.forecast_engine import (
            forecast_time_to_critical,
            TelemetryPoint,
        )
        from app.models.domain import (
            Object,
            Telemetry,
            Score,
            ScoreStatus,
        )
        from app.core.database import SessionLocal
        from sqlalchemy import desc, select

        telemetry_id = job_data.get("telemetry_id")
        object_id = job_data.get("object_id")

        db = SessionLocal()
        try:
            # 1. Load telemetry
            import uuid

            t = db.get(Telemetry, uuid.UUID(telemetry_id)) if telemetry_id else None
            obj = db.get(Object, uuid.UUID(object_id)) if object_id else None

            if t is None or obj is None:
                logger.warning("ARQ job %s: telemetry/object not found", job_id)
                return {"status": "skipped", "reason": "not_found"}

            # 2. Build features
            features = ScoreFeatures(
                battery_pct=t.battery_pct,
                battery_est_hours=t.battery_est_hours,
                temp_c=t.temp_c,
                co2_ppm=t.co2_ppm,
                occupancy_ratio=(
                    t.occupancy / obj.capacity if obj.capacity > 0 else 0.0
                ),
                criticality=obj.criticality,
                has_generator=obj.has_generator,
                has_starlink=obj.has_starlink,
                power_on=t.power_on,
                internet_on=t.internet_on,
                signal=t.signal,
                humidity_pct=t.humidity_pct,
                generator_on=t.generator_on,
            )

            # 3. ML inference
            pred = predict_score(features)

            # 4. Anomaly detection
            feature_vector = _build_features_from_telemetry(t, obj)
            anomaly_score = None
            try:
                detector = get_anomaly_detector()
                anomaly_score = detector.score(str(t.object_id), feature_vector)
            except Exception as e:
                logger.debug("Anomaly check failed: %s", e)

            # 5. Drift observation
            try:
                drift_det = get_drift_detector()
                drift_det.observe(feature_vector)
            except Exception as e:
                logger.debug("Drift observe failed: %s", e)

            # 6. Forecast
            history = list(
                db.scalars(
                    select(Telemetry)
                    .where(Telemetry.object_id == t.object_id)
                    .order_by(desc(Telemetry.ts))
                    .limit(24)
                )
            )[::-1]
            points = [
                TelemetryPoint(
                    ts=r.ts.timestamp(),
                    battery_pct=r.battery_pct,
                    power_on=r.power_on,
                    battery_est_hours=r.battery_est_hours,
                )
                for r in history
            ]
            forecast = forecast_time_to_critical(points)

            # 7. Persist Score
            status = pred.status
            if (
                forecast.time_to_critical_min is not None
                and forecast.time_to_critical_min <= 0
            ):
                status = "CRITICAL"
            elif (
                forecast.time_to_critical_min is not None
                and forecast.time_to_critical_min < 30
                and status == "STABLE"
            ):
                status = "CRITICAL"

            contribs = explain_score(features)
            score = Score(
                object_id=t.object_id,
                score=pred.score,
                status=ScoreStatus(status),
                time_to_critical_min=forecast.time_to_critical_min,
                components={
                    "model_version": "async",
                    "ml_prediction_confidence": pred.confidence,
                    "ml_tree_spread": pred.tree_spread,
                    "ml_feature_contributions": contribs,
                    "async_processed": True,
                    "job_id": job_id,
                    **(
                        {
                            "anomaly_score": anomaly_score.score,
                            "anomaly_is_anomaly": anomaly_score.is_anomaly,
                        }
                        if anomaly_score is not None
                        else {}
                    ),
                    "forecast_slope_pct_per_min": forecast.slope_pct_per_min,
                    "forecast_confidence": forecast.confidence,
                },
            )
            db.add(score)
            db.commit()

            elapsed = time.time() - start
            logger.info(
                "ARQ job %s completed in %.3fs (score=%.1f)",
                job_id,
                elapsed,
                pred.score,
            )
            return {
                "status": "ok",
                "score": pred.score,
                "ml_status": pred.status,
                "elapsed_sec": elapsed,
            }
        finally:
            db.close()
    except Exception as e:
        logger.exception("ARQ job %s failed: %s", job_id, e)
        return {"status": "error", "error": str(e)}


# ─────────────────────────────────────────────────────────────────────
# ARQ Worker Settings
# ─────────────────────────────────────────────────────────────────────
async def _startup(ctx: dict[str, Any]) -> None:
    """Worker startup hook."""
    logger.info("ARQ worker starting (queue=%s)", CONFIG.queue_name)


async def _shutdown(ctx: dict[str, Any]) -> None:
    """Worker shutdown hook."""
    logger.info("ARQ worker shutting down")


def get_worker_settings() -> dict[str, Any]:
    """Повертає settings для запуску ARQ worker."""
    from arq.connections import RedisSettings, create_pool

    return {
        "functions": [process_telemetry_job],
        "on_startup": _startup,
        "on_shutdown": _shutdown,
        "redis_settings": RedisSettings.from_dsn(CONFIG.redis_url),
        "max_jobs": CONFIG.max_jobs,
        "job_timeout": CONFIG.job_timeout_sec,
        "queue_name": CONFIG.queue_name,
    }


# ─────────────────────────────────────────────────────────────────────
# Enqueue API
# ─────────────────────────────────────────────────────────────────────
_async_pool: Optional[Any] = None


async def _get_pool() -> Optional[Any]:
    """Lazy-init ARQ pool."""
    global _async_pool
    if _async_pool is None and CONFIG.enabled:
        try:
            from arq.connections import create_pool, RedisSettings

            _async_pool = await create_pool(RedisSettings.from_dsn(CONFIG.redis_url))
            logger.info("ARQ pool initialized")
        except Exception as e:
            logger.warning("ARQ pool init failed: %s", e)
            _async_pool = None
    return _async_pool


async def enqueue_telemetry_processing(
    job_id: str, telemetry_id: str, object_id: str
) -> bool:
    """
    Додає job в ARQ queue.

    Returns:
        True якщо enqueued, False якщо Redis недоступний
        (тоді caller має fallback на sync).
    """
    pool = await _get_pool()
    if pool is None:
        return False

    try:
        import time

        await pool.enqueue_job(
            "process_telemetry_job",
            {
                "job_id": job_id,
                "telemetry_id": telemetry_id,
                "object_id": object_id,
                "enqueued_at": time.time(),
            },
        )
        return True
    except Exception as e:
        logger.warning("ARQ enqueue failed: %s", e)
        return False


def is_async_available() -> bool:
    """Перевіряє чи ARQ налаштовано."""
    return CONFIG.enabled
