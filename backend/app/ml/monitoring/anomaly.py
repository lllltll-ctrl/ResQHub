"""
Anomaly detection на telemetry data.

Використовує Isolation Forest для виявлення:
  - Зламаних сенсорів (наприклад, CO2 раптом = 0 або battery_pct = 999)
  - Неможливих комбінацій (наприклад, occupancy > capacity + generator_on = True)
  - Outlier readings в multi-variate space
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np
from sklearn.ensemble import IsolationForest

from app.ml.features import FEATURE_NAMES
from app.ml.store import ARTIFACTS_DIR, save_artifact, load_artifact

logger = logging.getLogger(__name__)

ANOMALY_MODEL_NAME = "anomaly_detector"
ANOMALY_REPORT_PATH = ARTIFACTS_DIR / "anomaly_report.json"
ANOMALY_MODEL_VERSION = "1.0.0"

ANOMALY_THRESHOLD_DEFAULT = -0.05  # decision_function boundary
ROLLING_WINDOW = 200


@dataclass
class AnomalyScore:
    """Anomaly score для одного telemetry-рядка."""

    object_id: str
    timestamp: float
    score: float  # нижче = більш аномально
    is_anomaly: bool
    feature_values: dict[str, float]
    top_anomalous_features: list[tuple[str, float]] = field(default_factory=list)
    reason: str = ""


@dataclass
class AnomalyReport:
    timestamp: float
    n_observations: int
    n_anomalies: int
    anomaly_rate: float
    anomalies: list[AnomalyScore] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "n_observations": self.n_observations,
            "n_anomalies": self.n_anomalies,
            "anomaly_rate": self.anomaly_rate,
            "anomalies": [asdict(a) for a in self.anomalies],
        }


class AnomalyDetector:
    """
    Isolation Forest-based anomaly detector.

    Lifecycle:
      1. fit(reference_data) — тренування на нормальних даних
      2. score(observation) — повертає AnomalyScore
      3. health_check() — перевірка стану detector
    """

    def __init__(
        self,
        contamination: float = 0.05,
        threshold: float = ANOMALY_THRESHOLD_DEFAULT,
    ) -> None:
        self._contamination = contamination
        self._threshold = threshold
        self._model: Optional[IsolationForest] = None
        self._feature_means: Optional[np.ndarray] = None
        self._feature_stds: Optional[np.ndarray] = None
        self._lock = threading.Lock()
        self._recent: deque[AnomalyScore] = deque(maxlen=ROLLING_WINDOW)

    def fit(self, X: np.ndarray) -> None:
        """Тренує Isolation Forest на reference data."""
        with self._lock:
            X = np.asarray(X, dtype=np.float64)
            self._feature_means = X.mean(axis=0)
            self._feature_stds = X.std(axis=0) + 1e-9
            X_norm = (X - self._feature_means) / self._feature_stds

            self._model = IsolationForest(
                n_estimators=200,
                max_samples="auto",
                contamination=self._contamination,
                random_state=42,
                n_jobs=-1,
            )
            self._model.fit(X_norm)
            save_artifact(
                ANOMALY_MODEL_NAME,
                {
                    "model": self._model,
                    "feature_means": self._feature_means,
                    "feature_stds": self._feature_stds,
                    "threshold": self._threshold,
                    "version": ANOMALY_MODEL_VERSION,
                },
            )
            logger.info(
                "Anomaly detector trained on %d samples, %d features",
                X.shape[0],
                X.shape[1],
            )

    def load(self) -> bool:
        """Завантажує попередньо натреновану модель."""
        try:
            data = load_artifact(ANOMALY_MODEL_NAME)
            with self._lock:
                self._model = data["model"]
                self._feature_means = data["feature_means"]
                self._feature_stds = data["feature_stds"]
                self._threshold = float(
                    data.get("threshold", ANOMALY_THRESHOLD_DEFAULT)
                )
            return True
        except FileNotFoundError:
            return False

    def _ensure_loaded(self) -> None:
        if self._model is None:
            if not self.load():
                # Auto-fit якщо немає артефакту
                from app.ml.dataset import generate_dataset

                bundle = generate_dataset(n_samples=2000, seed=42)
                self.fit(bundle.X)

    def score(
        self, object_id: str, x: np.ndarray, return_features: bool = True
    ) -> AnomalyScore:
        """Оцінює один observation."""
        self._ensure_loaded()
        with self._lock:
            assert self._model is not None
            assert self._feature_means is not None
            assert self._feature_stds is not None

            x = np.asarray(x, dtype=np.float64).flatten()
            x_norm = (x - self._feature_means) / self._feature_stds
            score = float(self._model.decision_function(x_norm.reshape(1, -1))[0])
            is_anomaly = bool(score < self._threshold)

            # Compute per-feature z-score для з'ясування "що саме аномальне"
            z_scores = np.abs(x_norm)
            top_idx = np.argsort(-z_scores)[:3]
            top_features = [(FEATURE_NAMES[i], float(x[i])) for i in top_idx]

            reason = _explain_anomaly(x, is_anomaly, top_features) if is_anomaly else ""

            result = AnomalyScore(
                object_id=object_id,
                timestamp=time.time(),
                score=score,
                is_anomaly=is_anomaly,
                feature_values=(
                    {n: float(x[i]) for i, n in enumerate(FEATURE_NAMES)}
                    if return_features
                    else {}
                ),
                top_anomalous_features=top_features,
                reason=reason,
            )
            self._recent.append(result)
            return result

    def recent_anomalies(self, limit: int = 20) -> list[AnomalyScore]:
        """Повертає останні anomalies."""
        with self._lock:
            anomalies = [a for a in self._recent if a.is_anomaly]
        return anomalies[-limit:]

    def health_check(self) -> dict[str, Any]:
        """Перевірка стану detector."""
        with self._lock:
            n_recent = len(self._recent)
            n_anom = sum(1 for a in self._recent if a.is_anomaly)
        return {
            "is_fitted": self._model is not None,
            "n_recent_observations": n_recent,
            "n_recent_anomalies": n_anom,
            "anomaly_rate_recent": (n_anom / n_recent if n_recent > 0 else 0.0),
            "threshold": self._threshold,
            "model_version": ANOMALY_MODEL_VERSION,
        }


def _explain_anomaly(
    x: np.ndarray, is_anomaly: bool, top_features: list[tuple[str, float]]
) -> str:
    """Генерує людино-читабельне пояснення аномалії."""
    if not is_anomaly:
        return ""
    parts: list[str] = []
    for name, val in top_features[:2]:
        parts.append(f"{name}={val:.1f}")
    return "Anomalous reading: " + ", ".join(parts)


# ─────────────────────────────────────────────────────────────────────
# Global singleton
# ─────────────────────────────────────────────────────────────────────
_global_detector: Optional[AnomalyDetector] = None


def get_anomaly_detector() -> AnomalyDetector:
    global _global_detector
    if _global_detector is None:
        _global_detector = AnomalyDetector()
        _global_detector.load()  # Спроба завантажити; якщо немає — fit згенерує
    return _global_detector
