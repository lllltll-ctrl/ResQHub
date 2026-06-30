"""
Online learning module для score model.

Використовує sklearn SGDRegressor (supports partial_fit) для адаптації
до нових патернів блекаутів без повного перетренування.

Lifecycle:
  1. Cold start: ініціалізуємо з нуля (n=0)
  2. Warm-up: перші 50 partial_fit calls
  3. Online: predict_and_learn() кожен раз приходить новий observation
  4. Drift response: якщо concept drift detector спрацював → reset

Використовується паралельно з batch-trained RandomForest як "online shadow model".
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np
from sklearn.linear_model import SGDRegressor
from sklearn.preprocessing import StandardScaler

from app.ml.features import FEATURE_NAMES
from app.ml.store import ARTIFACTS_DIR, load_artifact, save_artifact

logger = logging.getLogger(__name__)

ONLINE_MODEL_NAME = "online_scorer"
ONLINE_MODEL_VERSION = "1.0.0"
ONLINE_STATE_PATH = ARTIFACTS_DIR / f"online_scorer_state.json"

WARMUP_THRESHOLD = 50
DRIFT_WINDOW = 30
DRIFT_THRESHOLD = 0.15  # MAE різниця для спрацювання drift


@dataclass
class OnlineLearningState:
    """Стан online learner."""

    n_observations: int = 0
    n_warmup_complete: int = 0
    n_drifts_detected: int = 0
    last_drift_at: Optional[float] = None
    recent_mae: list[float] = field(default_factory=list)
    last_trained_at: float = field(default_factory=time.time)
    is_warm: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class OnlineScorer:
    """
    SGDRegressor-based online scorer з concept drift detection.

    Особливості:
      - StandardScaler фіч (для стабільної збіжності)
      - Learning rate schedule (адаптивний)
      - ADWIN-like concept drift detector (спрощений)
      - Persisted state на диск
    """

    def __init__(self) -> None:
        self._model: Optional[SGDRegressor] = None
        self._scaler: Optional[StandardScaler] = None
        self._state = OnlineLearningState()
        self._drift_window_mae: list[float] = []
        self._baseline_mae: float = 0.0
        self._loaded = False

    def _ensure_initialized(self) -> None:
        """Lazy init model + load state."""
        if self._loaded:
            return
        try:
            artifact = load_artifact(ONLINE_MODEL_NAME)
            self._model = artifact["model"]
            self._scaler = artifact["scaler"]
            self._state = OnlineLearningState(**artifact.get("state", {}))
            logger.info(
                "OnlineScorer loaded: n_obs=%d, warm=%s",
                self._state.n_observations,
                self._state.is_warm,
            )
        except FileNotFoundError:
            # Cold start
            self._model = SGDRegressor(
                loss="squared_error",
                learning_rate="adaptive",
                eta0=0.01,
                random_state=42,
                warm_start=True,
                max_iter=1,
            )
            self._scaler = StandardScaler()
            # Pre-warm with dummy fit to avoid NotFittedError on first predict
            dummy_X = np.zeros((1, len(FEATURE_NAMES)), dtype=np.float64)
            self._scaler.partial_fit(dummy_X)
            self._model.partial_fit(dummy_X, [50.0])
            logger.info("OnlineScorer initialized (cold start)")
        self._loaded = True

    def predict_and_learn(
        self,
        features: np.ndarray,
        target: Optional[float] = None,
    ) -> dict[str, Any]:
        """
        Predict score та (опційно) оновити модель.

        Args:
            features: 13D feature vector
            target: ground truth score (якщо відомий, для learning)

        Returns:
            dict з prediction, model_mae, drift_detected
        """
        self._ensure_initialized()
        assert self._model is not None
        assert self._scaler is not None

        features = np.asarray(features, dtype=np.float64).reshape(1, -1)

        # Scale
        features_scaled = self._scaler.transform(features)

        # Predict
        try:
            prediction = float(self._model.predict(features_scaled)[0])
        except Exception:
            # Fallback: якщо SGD не warmed up — return 50.0
            prediction = 50.0
        prediction = float(np.clip(prediction, 0.0, 100.0))

        # Update
        drift_detected = False
        learn_error: Optional[float] = None
        if target is not None:
            target = float(np.clip(target, 0.0, 100.0))
            self._model.partial_fit(features_scaled, [target])
            self._scaler.partial_fit(features)

            learn_error = abs(prediction - target)
            self._drift_window_mae.append(learn_error)
            if len(self._drift_window_mae) > DRIFT_WINDOW:
                self._drift_window_mae.pop(0)

            self._state.n_observations += 1
            if (
                self._state.n_observations >= WARMUP_THRESHOLD
                and not self._state.is_warm
            ):
                self._state.is_warm = True
                self._state.n_warmup_complete = self._state.n_observations
                self._baseline_mae = float(np.mean(self._drift_window_mae))
                logger.info("OnlineScorer warmed up (n=%d)", self._state.n_observations)

            # Concept drift detection
            if self._state.is_warm and len(self._drift_window_mae) == DRIFT_WINDOW:
                recent = float(np.mean(self._drift_window_mae))
                if recent > self._baseline_mae * (1 + DRIFT_THRESHOLD) and recent > 5.0:
                    # Drift detected!
                    drift_detected = True
                    self._state.n_drifts_detected += 1
                    self._state.last_drift_at = time.time()
                    logger.warning(
                        "Concept drift detected: recent_mae=%.2f vs baseline=%.2f",
                        recent,
                        self._baseline_mae,
                    )
                    # Adaptive response: bump learning rate temporarily
                    # (SGDRegressor не має прямого API, але можна скинути)
                    self._drift_window_mae.clear()
                    self._baseline_mae = recent

            self._state.last_trained_at = time.time()

        return {
            "prediction": round(prediction, 2),
            "learn_error": round(learn_error, 2) if learn_error is not None else None,
            "drift_detected": drift_detected,
            "is_warm": self._state.is_warm,
            "n_observations": self._state.n_observations,
        }

    def predict(self, features: np.ndarray) -> float:
        """Тільки predict, без learning."""
        result = self.predict_and_learn(features, target=None)
        return result["prediction"]

    def save(self) -> Path:
        """Серіалізує model + state на диск."""
        self._ensure_initialized()
        path = save_artifact(
            ONLINE_MODEL_NAME,
            {
                "model": self._model,
                "scaler": self._scaler,
                "state": self._state.to_dict(),
                "version": ONLINE_MODEL_VERSION,
            },
        )
        return path

    def reset(self) -> None:
        """Повний reset online learner (cold start)."""
        logger.warning("Resetting OnlineScorer")
        self._model = None
        self._scaler = None
        self._state = OnlineLearningState()
        self._drift_window_mae.clear()
        self._loaded = False
        self._ensure_initialized()

    def health_check(self) -> dict[str, Any]:
        """Повертає стан online learner."""
        self._ensure_initialized()
        recent_mae = (
            float(np.mean(self._drift_window_mae)) if self._drift_window_mae else None
        )
        return {
            "is_loaded": self._loaded,
            "is_warm": self._state.is_warm,
            "n_observations": self._state.n_observations,
            "n_drifts_detected": self._state.n_drifts_detected,
            "last_drift_at": self._state.last_drift_at,
            "recent_mae": recent_mae,
            "baseline_mae": self._baseline_mae,
            "model_version": ONLINE_MODEL_VERSION,
        }


# ─────────────────────────────────────────────────────────────────────
# Global singleton
# ─────────────────────────────────────────────────────────────────────
_global_scorer: Optional[OnlineScorer] = None


def get_online_scorer() -> OnlineScorer:
    global _global_scorer
    if _global_scorer is None:
        _global_scorer = OnlineScorer()
        _global_scorer._ensure_initialized()
    return _global_scorer
