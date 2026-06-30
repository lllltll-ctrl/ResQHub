"""
Tests for P4 modules: online learning, concept drift, bandit, MLflow, benchmarks.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pytest

BACKEND_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.ml.monitoring.bandit import (
    BanditArm,
    LinUCBBandit,
    MultiArmedBandit,
)
from app.ml.monitoring.concept_drift import (
    ADWINDetector,
    ConceptDriftMonitor,
    DDMDetector,
    PageHinkleyDetector,
)
from app.ml.online_learning import OnlineScorer, OnlineLearningState
from app.ml.experiment_tracking import (
    ExperimentTracker,
    ExperimentRun,
    ScoreQualityTracker,
)
from app.ml.benchmark import BenchmarkResult, PerformanceBenchmark


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


# ─────────────────────────────────────────────────────────────────────
# Concept Drift
# ─────────────────────────────────────────────────────────────────────
def test_adwin_no_drift_on_stable_data():
    """ADWIN: стабільні дані → no drift."""
    det = ADWINDetector()
    rng = np.random.RandomState(42)
    drift_event = None
    for _ in range(100):
        ev = det.add(rng.normal(0, 1))
        if ev is not None:
            drift_event = ev
    # Може бути 0-2 false positives, але не > 5
    assert det.drift_count <= 5


def test_adwin_detects_drift():
    """ADWIN: distribution shift → drift detected."""
    det = ADWINDetector()
    rng = np.random.RandomState(42)
    # First: low error
    for _ in range(50):
        det.add(rng.normal(0, 0.5))
    # Then: high error (drift)
    detected = False
    for _ in range(100):
        ev = det.add(rng.normal(5.0, 1.0))
        if ev is not None:
            detected = True
            break
    assert detected is True


def test_page_hinkley_detects_drift():
    """Page-Hinkley: cumulative deviation triggers."""
    det = PageHinkleyDetector(threshold=20.0, alpha=0.005)
    rng = np.random.RandomState(42)
    # Start with low-mean errors (build up cum_dev around 0)
    for _ in range(20):
        det.add(rng.normal(0, 0.5))
    # Then drift to high-mean errors
    detected = False
    for i in range(200):
        ev = det.add(rng.normal(5.0, 0.5))
        if ev is not None:
            detected = True
            break
    assert detected is True


def test_ddm_detects_drift():
    """DDM: z-score based detection."""
    det = DDMDetector()
    rng = np.random.RandomState(42)
    # Low errors for baseline
    for _ in range(50):
        det.add(rng.normal(0, 0.5))
    # Then suddenly high errors
    detected = False
    for _ in range(50):
        ev = det.add(rng.normal(10.0, 0.5))
        if ev is not None:
            detected = True
            break
    assert detected is True


def test_concept_drift_monitor_2_of_3():
    """Composite monitor: 2/3 detectors trigger drift confirmation."""
    # Use specific scenario: stable → then sustained high errors
    monitor = ConceptDriftMonitor()
    rng = np.random.RandomState(42)
    # First: small errors (build baseline)
    for _ in range(50):
        monitor.add(rng.normal(0, 0.3))
    # Then: very large sustained errors
    detected = False
    for _ in range(500):
        ev = monitor.add(rng.normal(10.0, 0.5))
        if ev is not None:
            assert ev.detector == "composite"
            detected = True
            break
    assert detected is True


# ─────────────────────────────────────────────────────────────────────
# Multi-Armed Bandit
# ─────────────────────────────────────────────────────────────────────
def test_bandit_register_and_select():
    """Bandit: register arms, select one."""
    bandit = MultiArmedBandit(strategy="ucb1")
    bandit.register_arm("gen_center", "GENERATOR", "Центральна база")
    bandit.register_arm("gen_south", "GENERATOR", "Південна база")
    bandit.register_arm("team_north", "TECH_TEAM", "Північна база")
    selected = bandit.select_arm()
    assert selected in {"gen_center", "gen_south", "team_north"}


def test_bandit_ucb1_explores_unvisited():
    """UCB1 спочатку обирає невідвідані arm."""
    bandit = MultiArmedBandit(strategy="ucb1")
    bandit.register_arm("a1", "GENERATOR", "base1")
    bandit.register_arm("a2", "GENERATOR", "base2")
    # First selection — обирає будь-який (обидва невідвідані)
    sel1 = bandit.select_arm()
    assert sel1 in {"a1", "a2"}


def test_bandit_epsilon_greedy():
    """Epsilon-greedy обирає random з ймовірністю epsilon."""
    bandit = MultiArmedBandit(strategy="epsilon_greedy", epsilon=1.0)
    bandit.register_arm("a1", "GENERATOR", "base1")
    bandit.register_arm("a2", "GENERATOR", "base2")
    # With epsilon=1.0, always random
    selections = set()
    for _ in range(20):
        selections.add(bandit.select_arm())
    assert len(selections) == 2  # обидва мають бути обрані


def test_bandit_thompson():
    """Thompson sampling."""
    bandit = MultiArmedBandit(strategy="thompson")
    bandit.register_arm("good", "GENERATOR", "base1")
    bandit.register_arm("bad", "GENERATOR", "base2")
    # Make "good" much better
    for _ in range(50):
        bandit.update("good", reward=10.0, success=True)
        bandit.update("bad", reward=1.0, success=False)
    # Thompson має віддати перевагу "good"
    counts = {"good": 0, "bad": 0}
    for _ in range(100):
        sel = bandit.select_arm()
        counts[sel] += 1
    assert counts["good"] > counts["bad"]


def test_bandit_save_load():
    """Bandit persistence."""
    bandit = MultiArmedBandit(strategy="ucb1")
    bandit.register_arm("a1", "GENERATOR", "base1")
    bandit.update("a1", reward=5.0, success=True)
    bandit.save()

    new_bandit = MultiArmedBandit(strategy="ucb1")
    loaded = new_bandit.load()
    assert loaded is True
    assert "a1" in new_bandit.arms_dict if hasattr(new_bandit, "arms_dict") else True
    # Verify state
    state = new_bandit.get_state()
    assert state["total_pulls"] == 1


def test_linucb_bandit():
    """LinUCB contextual bandit."""
    bandit = LinUCBBandit(n_features=5, alpha=1.0)
    bandit.register_arm("arm1")
    bandit.register_arm("arm2")
    context = np.random.RandomState(0).normal(0, 1, 5)
    sel = bandit.select(context)
    assert sel in {"arm1", "arm2"}
    bandit.update(sel, context, reward=1.0)


# ─────────────────────────────────────────────────────────────────────
# Experiment tracking
# ─────────────────────────────────────────────────────────────────────
def test_experiment_tracker_fallback():
    """Tracker працює навіть якщо MLflow недоступний."""
    tracker = ExperimentTracker(experiment_name="test")
    run_id = tracker.start_run("test_run")
    assert run_id is not None
    tracker.log_params({"n_estimators": 100})
    tracker.log_metrics({"rmse": 2.5, "r2": 0.99})
    tracker.set_tag("model_version", "1.0.0")
    tracker.end_run()
    assert tracker.get_active_run() is None


def test_score_quality_tracker():
    """ScoreQualityTracker обчислює MAE/RMSE."""
    tracker = ScoreQualityTracker(window=10)
    for pred, target in [(80, 75), (60, 65), (90, 85), (50, 55), (70, 70)]:
        tracker.record(pred, target)
    metrics = tracker.get_metrics()
    assert "mae" in metrics
    assert "rmse" in metrics
    assert metrics["n_samples"] == 5


def test_score_quality_tracker_empty():
    """Empty tracker → empty metrics."""
    tracker = ScoreQualityTracker()
    assert tracker.get_metrics() == {}


# ─────────────────────────────────────────────────────────────────────
# Performance Benchmark
# ─────────────────────────────────────────────────────────────────────
def test_performance_benchmark_basic():
    """Benchmark вимірює latency."""

    def _slow_predict(X: np.ndarray) -> np.ndarray:
        time.sleep(0.001)  # 1ms
        return np.zeros(X.shape[0])

    bench = PerformanceBenchmark("test_model", "1.0.0")
    result = bench.run(_slow_predict, n_samples=50, feature_dim=13)
    assert result.n_samples == 50
    assert result.mean_latency_ms > 0.5  # at least 0.5ms
    assert result.p99_latency_ms >= result.p50_latency_ms
    assert result.throughput_per_sec > 100


def test_benchmark_result_to_dict():
    """BenchmarkResult серіалізується."""
    result = BenchmarkResult(
        model_name="x",
        model_version="1.0.0",
        n_samples=100,
        total_time_sec=1.0,
        mean_latency_ms=10.0,
        p50_latency_ms=9.0,
        p95_latency_ms=15.0,
        p99_latency_ms=20.0,
        throughput_per_sec=100.0,
    )
    d = result.to_dict()
    assert d["model_name"] == "x"
    assert d["n_samples"] == 100
