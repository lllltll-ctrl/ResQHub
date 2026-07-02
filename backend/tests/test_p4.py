"""
Tests for P4 modules: online learning.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.ml.online_learning import OnlineScorer, OnlineLearningState


# ─────────────────────────────────────────────────────────────────────
# Online learning
# ─────────────────────────────────────────────────────────────────────
def test_online_scorer_cold_start():
    """Cold start: predict без ground truth."""
    scorer = OnlineScorer()
    features = np.random.RandomState(42).normal(0, 1, 13)
    result = scorer.predict_and_learn(features, target=None)
    assert "prediction" in result
    assert result["n_observations"] == 0
    assert result["is_warm"] is False


def test_online_scorer_warmup():
    """Warmup: 50+ observations trigger is_warm=True."""
    scorer = OnlineScorer()
    rng = np.random.RandomState(42)
    for i in range(60):
        features = rng.normal(0, 1, 13)
        target = float(rng.normal(0, 1))
        result = scorer.predict_and_learn(features, target=target)
    assert result["n_observations"] >= 50
    assert result["is_warm"] is True


def test_online_scorer_prediction_range():
    """Predictions обмежені 0-100."""
    scorer = OnlineScorer()
    rng = np.random.RandomState(42)
    for _ in range(30):
        features = rng.normal(0, 1, 13)
        result = scorer.predict_and_learn(features, target=50.0)
        assert 0.0 <= result["prediction"] <= 100.0


def test_online_scorer_health_check():
    """health_check повертає коректну структуру."""
    scorer = OnlineScorer()
    health = scorer.health_check()
    assert "is_loaded" in health
    assert "is_warm" in health
    assert "n_observations" in health
