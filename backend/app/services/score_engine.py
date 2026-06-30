"""
Resilience Score Engine (v2) — ML-версія.

Використовує натреновану RandomForestRegressor з app.ml.inference.
Без hard-coded magic constants: всі модифікатори — фічі моделі.

Тренування: `python -m app.ml.train`
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from app.ml.explain import explain_score
from app.ml.features import ScoreFeatures
from app.ml.inference import predict_score as ml_predict_score
from app.models.domain import ScoreStatus

CRITICAL_BATTERY_PCT = 20.0
CRITICAL_BATTERY_HOURS = 2.0


@dataclass(frozen=True)
class ScoreInput:
    battery_pct: float
    battery_est_hours: float
    power_on: bool
    temp_c: float
    co2_ppm: float
    signal: int
    internet_on: bool
    occupancy: int
    capacity: int
    criticality: int
    has_generator: bool
    has_starlink: bool
    generator_on: bool = False
    humidity_pct: float = 50.0

    def to_features(self) -> ScoreFeatures:
        occ_ratio = (self.occupancy / self.capacity) if self.capacity > 0 else 0.0
        return ScoreFeatures(
            battery_pct=float(np.clip(self.battery_pct, 0, 100)),
            battery_est_hours=float(self.battery_est_hours),
            temp_c=float(self.temp_c),
            co2_ppm=float(self.co2_ppm),
            occupancy_ratio=float(occ_ratio),
            criticality=int(self.criticality),
            has_generator=bool(self.has_generator),
            has_starlink=bool(self.has_starlink),
            power_on=bool(self.power_on),
            internet_on=bool(self.internet_on),
            signal=int(self.signal),
            humidity_pct=float(self.humidity_pct),
            generator_on=bool(self.generator_on),
        )


@dataclass(frozen=True)
class ScoreResult:
    score: float
    status: ScoreStatus
    components: dict


def compute_score(inp: ScoreInput) -> ScoreResult:
    """
    Прогнозує Resilience Score за допомогою натренованого ML-моделі.
    Повертає компоненти для дебагу та пояснення журі.
    """
    features = inp.to_features()
    prediction = ml_predict_score(features)
    contributions = explain_score(features)

    components = {
        "model_version": _model_version(),
        "ml_prediction_confidence": prediction.confidence,
        "ml_tree_spread": prediction.tree_spread,
        "ml_feature_contributions": contributions,
        "ml_features_used": [
            "battery_pct",
            "battery_est_hours",
            "temp_c",
            "co2_ppm",
            "occupancy_ratio",
            "criticality",
            "has_generator",
            "has_starlink",
            "power_on",
            "internet_on",
            "signal",
            "humidity_pct",
            "generator_on",
        ],
        "input_battery_pct": round(inp.battery_pct, 1),
        "input_co2_ppm": round(inp.co2_ppm, 1),
        "input_occupancy_ratio": round(
            (inp.occupancy / inp.capacity) if inp.capacity > 0 else 0.0, 3
        ),
    }

    status = _status_from_string(prediction.status)
    return ScoreResult(
        score=prediction.score,
        status=status,
        components=components,
    )


def _status_from_string(s: str) -> ScoreStatus:
    return {
        "STABLE": ScoreStatus.STABLE,
        "WARNING": ScoreStatus.WARNING,
        "CRITICAL": ScoreStatus.CRITICAL,
    }[s]


def _model_version() -> str:
    try:
        from app.ml.inference import model_versions

        return model_versions()["score_model"]
    except Exception:
        return "unknown"
