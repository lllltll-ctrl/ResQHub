"""
Unit tests for P2 monitoring modules: drift + anomaly.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.ml.monitoring.drift import DriftDetector, FeatureDrift
from app.ml.monitoring.anomaly import AnomalyDetector
from app.ml.features import FEATURE_NAMES


# ─────────────────────────────────────────────────────────────────────
# Drift detector
# ─────────────────────────────────────────────────────────────────────
def test_drift_detector_set_reference_and_observe():
    """Drift detector приймає reference і observations."""
    det = DriftDetector(window_size=50)
    ref = np.random.RandomState(42).normal(0, 1, (100, 13))
    det.set_reference(ref)
    for _ in range(20):
        det.observe(np.random.RandomState(0).normal(0, 1, 13))
    assert det._reference is not None
    assert len(det._current) == 20


def test_drift_detector_no_drift_when_distributions_match():
    """Якщо reference і current з того ж розподілу — drift не виявлено."""
    det = DriftDetector(window_size=100)
    rng = np.random.RandomState(42)
    ref = rng.normal(0, 1, (500, 13))
    det.set_reference(ref)
    # Додаємо current з ТОГО САМОГО розподілу
    for _ in range(100):
        det.observe(rng.normal(0, 1, 13))

    report = det.check_drift()
    assert report.n_current == 100
    # Може бути 0-1 false positive, але не > 5
    assert report.n_drifted <= 5, f"Too many false positives: {report.drifted_features}"


def test_drift_detector_detects_drift():
    """Якщо current має зсув — drift виявлено."""
    det = DriftDetector(window_size=200)
    rng = np.random.RandomState(42)
    ref = rng.normal(0, 1, (500, 13))
    det.set_reference(ref)
    # Додаємо current з ІНШОГО розподілу (mean=5, std=1)
    for _ in range(200):
        det.observe(np.random.RandomState(99).normal(5.0, 1.0, 13))

    report = det.check_drift()
    assert report.n_drifted > 0
    assert "battery_pct" in report.drifted_features  # First feature


def test_drift_detector_insufficient_data():
    """З < 30 observations — report порожній."""
    det = DriftDetector(window_size=100)
    det.set_reference(np.zeros((100, 13)))
    det.observe(np.zeros(13))
    det.observe(np.ones(13) * 5)
    report = det.check_drift()
    assert report.n_drifted == 0
    assert "n_current" in report.to_dict()


# ─────────────────────────────────────────────────────────────────────
# Anomaly detector
# ─────────────────────────────────────────────────────────────────────
def test_anomaly_detector_fit_and_score():
    """Anomaly detector тренується і робить score."""
    det = AnomalyDetector(contamination=0.05)
    rng = np.random.RandomState(42)
    # Generate "normal" data
    X = rng.normal(50, 10, (500, 13))
    det.fit(X)

    # Score normal point
    score_normal = det.score("obj-1", rng.normal(50, 10, 13))
    # Score anomaly
    score_anomaly = det.score(
        "obj-2",
        np.array([200, 200, 200, 200, 200, 5, 0, 0, 0, 0, 0, 0, 0], dtype=np.float64),
    )

    assert score_normal.score > score_anomaly.score, (
        f"Normal score ({score_normal.score}) should be > anomaly ({score_anomaly.score})"
    )
    assert not score_normal.is_anomaly
    assert score_anomaly.is_anomaly


def test_anomaly_detector_health_check():
    """health_check повертає коректну структуру."""
    det = AnomalyDetector()
    det.fit(np.random.RandomState(0).normal(0, 1, (200, 13)))
    health = det.health_check()
    assert "is_fitted" in health
    assert health["is_fitted"] is True
    assert "threshold" in health
    assert "model_version" in health


def test_anomaly_detector_load_persists():
    """Anomaly detector зберігає і завантажує артефакт."""
    from app.ml.store import ARTIFACTS_DIR, load_artifact

    det1 = AnomalyDetector()
    X = np.random.RandomState(42).normal(50, 5, (300, 13))
    det1.fit(X)

    det2 = AnomalyDetector()
    loaded = det2.load()
    assert loaded is True

    # Score має збігатися
    test_x = X[0]
    s1 = det1.score("test", test_x)
    s2 = det2.score("test", test_x)
    assert abs(s1.score - s2.score) < 1e-6
