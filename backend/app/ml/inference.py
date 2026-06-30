"""
Inference-only module: load trained models and produce predictions.

НЕ МІСТИТЬ training-коду. Усе тренування — у train.py.
Моделі завантажуються ЛИШЕ ОДНОРАЗОВО при старті процесу (module-level cache),
а не при кожному виклику predict().
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Optional

import numpy as np

from app.ml.features import FEATURE_NAMES, ScoreFeatures
from app.ml.store import (
    RANKER_MODEL_PATH,
    RANKER_MODEL_VERSION,
    SCORE_MODEL_PATH,
    SCORE_MODEL_VERSION,
    load_artifact,
)

_lock = threading.Lock()
_score_artifact: Optional[dict] = None
_ranker_artifact: Optional[dict] = None


def _load_score() -> dict:
    global _score_artifact
    if _score_artifact is None:
        with _lock:
            if _score_artifact is None:
                _score_artifact = load_artifact(f"score_model_{SCORE_MODEL_VERSION}")
    return _score_artifact


def _load_ranker() -> dict:
    global _ranker_artifact
    if _ranker_artifact is None:
        with _lock:
            if _ranker_artifact is None:
                _ranker_artifact = load_artifact(f"ranker_model_{RANKER_MODEL_VERSION}")
    return _ranker_artifact


@dataclass(frozen=True)
class ScorePrediction:
    score: float
    status: str
    confidence: float
    tree_spread: float
    regressor: object


@dataclass(frozen=True)
class RankerPrediction:
    """Сирий результат ranker-моделі + рекомендований ресурс."""

    priority_score: float
    feature_contributions: dict[str, float]


def predict_score(features: ScoreFeatures) -> ScorePrediction:
    """
    Інференс score-моделі: повертає (score, status, confidence, tree_spread).
    """
    artifact = _load_score()
    regressor = artifact["regressor"]
    X = features.to_array()
    raw = float(regressor.predict(X)[0])
    score = float(np.clip(raw, 0.0, 100.0))

    # Status threshold (з метаданих)
    thresholds = artifact.get("status_thresholds", {"stable": 70.0, "warning": 40.0})
    if score >= thresholds["stable"]:
        status = "STABLE"
    elif score >= thresholds["warning"]:
        status = "WARNING"
    else:
        status = "CRITICAL"

    # Tree spread (для RF/ET) — confidence proxy
    spread = 0.0
    confidence = 0.85
    try:
        estimators = regressor.estimators_
        tree_preds = np.array([est.predict(X)[0] for est in estimators])
        spread = float(tree_preds.std())
        confidence = float(np.clip(1.0 - spread / 50.0, 0.70, 0.99))
    except AttributeError:
        pass

    return ScorePrediction(
        score=round(score, 1),
        status=status,
        confidence=round(confidence, 2),
        tree_spread=round(spread, 2),
        regressor=regressor,
    )


def predict_ranker(features_array: np.ndarray) -> np.ndarray:
    """
    Інференс ranker-моделі: повертає priority_score для кожного об'єкта.
    features_array — (n, k) numpy-масив.
    """
    artifact = _load_ranker()
    model = artifact["model"]
    return model.predict(features_array)


def get_ranker_feature_names() -> list[str]:
    artifact = _load_ranker()
    return list(artifact.get("feature_names", []))


def model_versions() -> dict[str, str]:
    return {
        "score_model": SCORE_MODEL_VERSION,
        "ranker_model": RANKER_MODEL_VERSION,
    }


def score_feature_names() -> list[str]:
    return list(FEATURE_NAMES)
