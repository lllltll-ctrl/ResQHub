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


# ─────────────────────────────────────────────────────────────────────
# P3 Endpoints: time-series, counterfactual, RCA, ensemble, model cards
# ─────────────────────────────────────────────────────────────────────
@router.get("/forecast/timeseries/{object_id}")
def time_series_forecast(
    object_id: str,
    horizon_min: int = 240,
) -> dict[str, Any]:
    """Prophet-based time-series forecast для battery/CO2/occupancy."""
    from sqlalchemy import desc, select
    from app.core.database import SessionLocal
    from app.models.domain import Telemetry
    from app.ml.time_series import forecast_object_metrics

    try:
        oid = uuid.UUID(object_id)
    except ValueError:
        raise HTTPException(400, "Invalid object_id")

    db = SessionLocal()
    try:
        history = list(
            db.scalars(
                select(Telemetry)
                .where(Telemetry.object_id == oid)
                .order_by(desc(Telemetry.ts))
                .limit(500)
            )
        )[::-1]

        if len(history) < 5:
            raise HTTPException(404, "Insufficient history for forecast")

        battery_hist = [(r.ts.timestamp(), r.battery_pct) for r in history]
        co2_hist = [(r.ts.timestamp(), r.co2_ppm) for r in history]
        occ_hist = [(r.ts.timestamp(), r.occupancy) for r in history]

        forecast = forecast_object_metrics(
            object_id=object_id,
            battery_history=battery_hist,
            co2_history=co2_hist,
            occupancy_history=occ_hist,
            horizon_min=horizon_min,
        )

        return {
            "object_id": forecast.object_id,
            "horizon_min": forecast.horizon_min
            if hasattr(forecast, "horizon_min")
            else horizon_min,
            "generated_at": forecast.generated_at,
            "warnings": forecast.warnings,
            "battery": (
                {
                    "current": forecast.battery_forecast.current_value,
                    "predicted": forecast.battery_forecast.predicted_value,
                    "lower": forecast.battery_forecast.lower_bound,
                    "upper": forecast.battery_forecast.upper_bound,
                    "trend": forecast.battery_forecast.trend_direction,
                    "method": forecast.battery_forecast.method,
                    "confidence": forecast.battery_forecast.confidence,
                }
                if forecast.battery_forecast
                else None
            ),
            "co2": (
                {
                    "current": forecast.co2_forecast.current_value,
                    "predicted": forecast.co2_forecast.predicted_value,
                    "lower": forecast.co2_forecast.lower_bound,
                    "upper": forecast.co2_forecast.upper_bound,
                    "trend": forecast.co2_forecast.trend_direction,
                    "method": forecast.co2_forecast.method,
                }
                if forecast.co2_forecast
                else None
            ),
            "occupancy": (
                {
                    "current": forecast.occupancy_forecast.current_value,
                    "predicted": forecast.occupancy_forecast.predicted_value,
                    "lower": forecast.occupancy_forecast.lower_bound,
                    "upper": forecast.occupancy_forecast.upper_bound,
                    "trend": forecast.occupancy_forecast.trend_direction,
                    "method": forecast.occupancy_forecast.method,
                }
                if forecast.occupancy_forecast
                else None
            ),
        }
    finally:
        db.close()


class CounterfactualRequest(BaseModel):
    interventions: list[dict[str, Any]] = Field(
        ...,
        description="List of {object_id, intervention_type, eta_min, ...}",
    )


@router.post("/counterfactual")
def counterfactual_analysis(req: CounterfactualRequest) -> dict[str, Any]:
    """What-if analysis: симулює ефект interventions перед dispatch."""
    from sqlalchemy import desc, select
    from app.core.database import SessionLocal
    from app.models.domain import Object, Telemetry, Score
    from app.ml.counterfactual import (
        InterventionSpec,
        run_counterfactual,
    )
    from app.ml.features import ScoreFeatures

    db = SessionLocal()
    try:
        objects_data: list[tuple[str, str, ScoreFeatures]] = []
        for inv in req.interventions:
            try:
                oid = uuid.UUID(inv["object_id"])
            except (ValueError, KeyError):
                continue
            obj = db.get(Object, oid)
            if obj is None:
                continue
            last_t = db.scalars(
                select(Telemetry)
                .where(Telemetry.object_id == oid)
                .order_by(desc(Telemetry.ts))
                .limit(1)
            ).first()
            if last_t is None:
                continue
            occ_ratio = (last_t.occupancy / obj.capacity) if obj.capacity > 0 else 0.0
            features = ScoreFeatures(
                battery_pct=last_t.battery_pct,
                battery_est_hours=last_t.battery_est_hours,
                temp_c=last_t.temp_c,
                co2_ppm=last_t.co2_ppm,
                occupancy_ratio=occ_ratio,
                criticality=obj.criticality,
                has_generator=obj.has_generator,
                has_starlink=obj.has_starlink,
                power_on=last_t.power_on,
                internet_on=last_t.internet_on,
                signal=last_t.signal,
                humidity_pct=last_t.humidity_pct,
                generator_on=last_t.generator_on,
            )
            objects_data.append((str(oid), obj.name, features))

        # Build interventions
        interventions = []
        for inv in req.interventions:
            try:
                interventions.append(
                    InterventionSpec(
                        object_id=inv["object_id"],
                        intervention_type=inv.get("intervention_type", "generator"),
                        eta_min=inv.get("eta_min", 30),
                        effect_battery_pct=inv.get("effect_battery_pct", 100.0),
                        effect_occupancy_relief=inv.get("effect_occupancy_relief", 0.0),
                    )
                )
            except Exception:
                continue

        analysis = run_counterfactual(objects_data, interventions)
        return {
            "baseline_avg_score": analysis.baseline_avg_score,
            "post_intervention_avg_score": analysis.post_intervention_avg_score,
            "score_improvement": analysis.score_improvement,
            "baseline_critical_count": analysis.baseline_critical_count,
            "post_intervention_critical_count": analysis.post_intervention_critical_count,
            "critical_reduction": analysis.critical_reduction,
            "recommendation": analysis.recommendation,
            "interventions": [
                {
                    "object_id": r.object_id,
                    "object_name": r.object_name,
                    "before_score": r.before_score,
                    "after_score": r.after_score,
                    "score_delta": r.score_delta,
                    "before_status": r.before_status,
                    "after_status": r.after_status,
                    "will_rescue": r.will_rescue,
                }
                for r in analysis.intervention_results
            ],
        }
    finally:
        db.close()


@router.get("/rca/{object_id}")
def root_cause_analysis(object_id: str) -> dict[str, Any]:
    """Root-Cause Analysis для останньої аномалії об'єкта."""
    from app.ml.monitoring.anomaly import get_anomaly_detector
    from app.ml.monitoring.rca import get_rca
    from app.ml.monitoring.rca import ANOMALY_HISTORY_PATH
    import json

    if not ANOMALY_HISTORY_PATH.exists():
        return {"status": "no_history", "message": "No anomalies recorded yet"}

    # Find most recent anomaly for this object
    last_anomaly = None
    with ANOMALY_HISTORY_PATH.open() as f:
        for line in f:
            if line.strip():
                try:
                    d = json.loads(line)
                    if d.get("object_id") == object_id:
                        from app.ml.monitoring.anomaly import AnomalyScore

                        last_anomaly = AnomalyScore(
                            object_id=d["object_id"],
                            timestamp=d["timestamp"],
                            score=d["score"],
                            is_anomaly=True,
                            feature_values=d.get("feature_values", {}),
                        )
                except Exception:
                    continue

    if last_anomaly is None:
        return {"status": "no_anomaly", "message": f"No anomalies for {object_id}"}

    # Compute z-scores
    feature_values = last_anomaly.feature_values
    detector = get_anomaly_detector()
    z_scores: dict[str, float] = {}
    if detector._feature_means is not None and detector._feature_stds is not None:
        for name, val in feature_values.items():
            try:
                idx = next(
                    i
                    for i, n in enumerate(
                        __import__(
                            "app.ml.features", fromlist=["FEATURE_NAMES"]
                        ).FEATURE_NAMES
                    )
                    if n == name
                )
                z = (val - detector._feature_means[idx]) / detector._feature_stds[idx]
                z_scores[name] = round(float(z), 2)
            except Exception:
                pass

    rca = get_rca()
    analysis = rca.analyze(last_anomaly, feature_values, z_scores)

    return {
        "object_id": analysis.object_id,
        "timestamp": analysis.timestamp,
        "anomaly_score": analysis.anomaly_score,
        "primary_cause": analysis.primary_cause,
        "is_recurring": analysis.is_recurring,
        "similar_anomalies_last_24h": analysis.similar_anomalies_last_24h,
        "feature_deviations": analysis.feature_deviations,
        "root_causes": [
            {
                "cause": h.cause,
                "confidence": h.confidence,
                "evidence": h.evidence,
                "recommended_action": h.recommended_action,
            }
            for h in analysis.root_causes
        ],
        "recommended_action": analysis.recommended_action,
    }


@router.post("/ensemble/train")
def train_ensemble_endpoint(background: BackgroundTasks) -> dict[str, Any]:
    """Тренує multi-model ensemble (RF + XGBoost + LightGBM)."""
    job_id = str(uuid.uuid4())

    def _train() -> None:
        from app.ml.ensemble import train_ensemble

        try:
            train_ensemble()
        except Exception as e:
            logger.exception("Ensemble training failed: %s", e)

    background.add_task(_train)
    return {"status": "scheduled", "job_id": job_id}


@router.get("/ensemble/predict")
def ensemble_predict(features: list[float]) -> dict[str, Any]:
    """Прогноз через ensemble (13 features)."""
    from app.ml.features import FEATURE_NAMES, ScoreFeatures
    from app.ml.ensemble import predict_ensemble

    if len(features) != len(FEATURE_NAMES):
        raise HTTPException(400, f"Expected {len(FEATURE_NAMES)} features")

    feature_dict = dict(zip(FEATURE_NAMES, features))
    try:
        sf = ScoreFeatures(**feature_dict)
    except Exception as e:
        raise HTTPException(400, f"Invalid features: {e}")

    return predict_ensemble(sf)


@router.get("/model-cards")
def list_model_cards() -> dict[str, Any]:
    """Список усіх model cards."""
    from app.ml.model_cards import list_model_cards, get_model_card

    cards = {}
    for name in list_model_cards():
        card = get_model_card(name)
        if card:
            cards[name] = card.to_dict()
    return cards


@router.get("/model-cards/{model_name}")
def get_model_card_endpoint(model_name: str) -> dict[str, Any]:
    """Конкретна model card."""
    from app.ml.model_cards import get_model_card

    card = get_model_card(model_name)
    if card is None:
        raise HTTPException(404, f"Model card not found: {model_name}")
    return card.to_dict()


@router.get("/async/status")
def async_status() -> dict[str, Any]:
    """Статус async inference worker."""
    from app.ml.async_inference import CONFIG, is_async_available

    return {
        "enabled": CONFIG.enabled,
        "available": is_async_available(),
        "redis_url": CONFIG.redis_url,
        "queue_name": CONFIG.queue_name,
        "max_jobs": CONFIG.max_jobs,
        "job_timeout_sec": CONFIG.job_timeout_sec,
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


class BriefingRequest(BaseModel):
    object_id: str
    use_llm: bool = False


@router.post("/briefing")
def operator_briefing(req: BriefingRequest) -> dict[str, Any]:
    """Генерує людино-читабельний брифінг для оператора.

    Використовує ML score + SHAP + anomaly + drift context.
    """
    from app.ml.inference import predict_score
    from app.ml.monitoring.anomaly import get_anomaly_detector
    from app.ml.monitoring.drift import get_drift_detector
    from app.ml.operator_briefing import (
        generate_llm_briefing,
        generate_template_briefing,
    )
    from app.services.orchestrator import _build_features_from_telemetry
    from sqlalchemy import desc, select
    from app.core.database import SessionLocal
    from app.models.domain import Object, Telemetry, Score

    db = SessionLocal()
    try:
        try:
            oid = uuid.UUID(req.object_id)
        except ValueError:
            raise HTTPException(400, "Invalid object_id")

        obj = db.get(Object, oid)
        if obj is None:
            raise HTTPException(404, "Object not found")

        last_t = db.scalars(
            select(Telemetry)
            .where(Telemetry.object_id == oid)
            .order_by(desc(Telemetry.ts))
            .limit(1)
        ).first()

        if last_t is None:
            raise HTTPException(404, "No telemetry data")

        last_s = db.scalars(
            select(Score)
            .where(Score.object_id == oid)
            .order_by(desc(Score.ts))
            .limit(1)
        ).first()

        # Build features
        feature_vector = _build_features_from_telemetry(last_t, obj)
        from app.ml.features import ScoreFeatures

        features = ScoreFeatures(
            battery_pct=last_t.battery_pct,
            battery_est_hours=last_t.battery_est_hours,
            temp_c=last_t.temp_c,
            co2_ppm=last_t.co2_ppm,
            occupancy_ratio=(
                last_t.occupancy / obj.capacity if obj.capacity > 0 else 0.0
            ),
            criticality=obj.criticality,
            has_generator=obj.has_generator,
            has_starlink=obj.has_starlink,
            power_on=last_t.power_on,
            internet_on=last_t.internet_on,
            signal=last_t.signal,
            humidity_pct=last_t.humidity_pct,
            generator_on=last_t.generator_on,
        )

        pred = predict_score(features)

        # Anomaly check
        try:
            anomaly_score = get_anomaly_detector().score(req.object_id, feature_vector)
            anomaly_flag = anomaly_score.is_anomaly
        except Exception:
            anomaly_flag = False

        # Drift check (cheap, just look at report)
        try:
            from app.ml.monitoring.drift import DRIFT_REPORT_PATH
            import json

            if DRIFT_REPORT_PATH.exists():
                drift_report = json.loads(DRIFT_REPORT_PATH.read_text())
                drift_flag = drift_report.get("n_drifted", 0) > 0
            else:
                drift_flag = False
        except Exception:
            drift_flag = False

        ttc = last_s.time_to_critical_min if last_s else None

        if req.use_llm:
            briefing = generate_llm_briefing(
                object_name=obj.name,
                object_type=obj.type.value,
                features=features,
                ml_score=pred.score,
                ml_status=pred.status,
                ml_confidence=pred.confidence,
                anomaly_detected=anomaly_flag,
                drift_detected=drift_flag,
                ttc_minutes=ttc,
            )
        else:
            briefing = generate_template_briefing(
                object_name=obj.name,
                object_type=obj.type.value,
                features=features,
                ml_score=pred.score,
                ml_status=pred.status,
                ml_confidence=pred.confidence,
                anomaly_detected=anomaly_flag,
                drift_detected=drift_flag,
                ttc_minutes=ttc,
            )

        return {
            "object_id": req.object_id,
            "object_name": obj.name,
            "summary": briefing.summary,
            "severity": briefing.severity,
            "recommended_actions": briefing.recommended_actions,
            "key_factors": [
                {"feature": k, "shap_value": v} for k, v in briefing.key_factors
            ],
            "model_confidence": briefing.model_confidence,
            "method": briefing.method,
            "anomaly_detected": anomaly_flag,
            "drift_detected": drift_flag,
            "ttc_minutes": ttc,
        }
    finally:
        db.close()
