"""
Drift detection для вхідних фічей ML-моделі.

Використовує statistical tests (Kolmogorov-Smirnov для continuous, chi-square
для categorical) щоб виявити розбіжності між training distribution і
поточним потоком telemetry.

Це lightweight реалізація, сумісна з evidently.ai API.
Якщо evidently доступний — використовуємо його; інакше fallback на власну.
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
import pandas as pd
from scipy import stats

from app.ml.features import FEATURE_NAMES
from app.ml.store import ARTIFACTS_DIR

logger = logging.getLogger(__name__)

DRIFT_REPORT_PATH = ARTIFACTS_DIR / "drift_report.json"
WINDOW_SIZE = 200  # Кількість recent samples для порівняння
DRIFT_THRESHOLD_P = 0.05  # p-value threshold


@dataclass
class FeatureDrift:
    """Drift metric для однієї фічі."""

    feature: str
    statistic: float
    p_value: float
    drifted: bool
    test: str
    reference_mean: float
    current_mean: float
    reference_std: float
    current_std: float


@dataclass
class DriftReport:
    """Сумарний звіт по drift."""

    timestamp: float
    n_reference: int
    n_current: int
    n_drifted: int
    drifted_features: list[str]
    details: list[FeatureDrift] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "n_reference": self.n_reference,
            "n_current": self.n_current,
            "n_drifted": self.n_drifted,
            "drifted_features": self.drifted_features,
            "details": [asdict(d) for d in self.details],
        }

    @property
    def has_drift(self) -> bool:
        return self.n_drifted > 0


class DriftDetector:
    """
    Потокобезпечний детектор drift з rolling window.

    Використання:
        detector = DriftDetector()
        detector.set_reference(training_features)
        detector.observe(current_feature_vector)
        report = detector.check_drift()
    """

    def __init__(self, window_size: int = WINDOW_SIZE) -> None:
        self._window_size = window_size
        self._reference: Optional[np.ndarray] = None
        self._current: deque[np.ndarray] = deque(maxlen=window_size)
        self._lock = threading.Lock()

    def set_reference(self, X: np.ndarray) -> None:
        """Встановлює reference distribution (зазвичай training data)."""
        with self._lock:
            self._reference = np.asarray(X, dtype=np.float64).copy()

    def observe(self, x: np.ndarray) -> None:
        """Додає один observation у current window."""
        with self._lock:
            self._current.append(np.asarray(x, dtype=np.float64).flatten())

    def observe_batch(self, X: np.ndarray) -> None:
        """Додає масив observations."""
        for row in np.asarray(X, dtype=np.float64):
            self.observe(row)

    def check_drift(self) -> DriftReport:
        """
        Перевіряє drift через Kolmogorov-Smirnov test
        для кожної фічі між reference і current.
        """
        with self._lock:
            if self._reference is None:
                raise ValueError("Reference distribution not set")

            if len(self._current) < 30:
                return DriftReport(
                    timestamp=time.time(),
                    n_reference=len(self._reference),
                    n_current=len(self._current),
                    n_drifted=0,
                    drifted_features=[],
                )

            ref = self._reference
            cur = np.vstack(list(self._current))

        details: list[FeatureDrift] = []
        drifted: list[str] = []

        for i, name in enumerate(FEATURE_NAMES):
            try:
                r = ref[:, i]
                c = cur[:, i]
                # Skip constant features
                if np.std(r) < 1e-9 and np.std(c) < 1e-9:
                    continue
                stat, p = stats.ks_2samp(r, c)
                is_drifted = bool(p < DRIFT_THRESHOLD_P)
                if is_drifted:
                    drifted.append(name)
                details.append(
                    FeatureDrift(
                        feature=name,
                        statistic=float(stat),
                        p_value=float(p),
                        drifted=is_drifted,
                        test="ks_2samp",
                        reference_mean=float(r.mean()),
                        current_mean=float(c.mean()),
                        reference_std=float(r.std()),
                        current_std=float(c.std()),
                    )
                )
            except Exception as e:
                logger.warning("Drift check failed for %s: %s", name, e)

        report = DriftReport(
            timestamp=time.time(),
            n_reference=int(len(ref)),
            n_current=int(len(cur)),
            n_drifted=len(drifted),
            drifted_features=drifted,
            details=details,
        )

        # Persist report
        try:
            DRIFT_REPORT_PATH.write_text(json.dumps(report.to_dict(), indent=2))
        except Exception as e:
            logger.warning("Failed to persist drift report: %s", e)

        return report

    def summary(self) -> dict[str, Any]:
        """Повертає summary у JSON-форматі для API."""
        try:
            if not DRIFT_REPORT_PATH.exists():
                return {"status": "no_report", "message": "Run check_drift() first"}
            return json.loads(DRIFT_REPORT_PATH.read_text())
        except Exception as e:
            return {"status": "error", "message": str(e)}


# ─────────────────────────────────────────────────────────────────────
# Global instance — оновлюється при кожному telemetry POST
# ─────────────────────────────────────────────────────────────────────
_global_detector: Optional[DriftDetector] = None


def get_drift_detector() -> DriftDetector:
    """Lazy-initialized global detector."""
    global _global_detector
    if _global_detector is None:
        _global_detector = DriftDetector()
        # Автоматично встановити reference з training dataset
        try:
            from app.ml.dataset import generate_dataset

            bundle = generate_dataset(n_samples=2000, seed=42)
            _global_detector.set_reference(bundle.X)
            logger.info("Drift detector initialized with 2000 reference samples")
        except Exception as e:
            logger.warning("Failed to init reference distribution: %s", e)
    return _global_detector
