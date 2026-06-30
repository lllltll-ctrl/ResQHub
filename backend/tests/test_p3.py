"""
Tests for P3 modules: ensemble, counterfactual, RCA, time-series, model cards.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pytest

BACKEND_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.ml.counterfactual import (
    CounterfactualAnalysis,
    InterventionResult,
    InterventionSpec,
    analyze_intervention,
    run_counterfactual,
)
from app.ml.features import FEATURE_NAMES, ScoreFeatures
from app.ml.model_cards import (
    MODEL_CARDS,
    ModelCard,
    get_model_card,
    list_model_cards,
)
from app.ml.monitoring.rca import (
    ANOMALY_HISTORY_PATH,
    RootCauseAnalysis,
    RootCauseAnalyzer,
)
from app.ml.time_series import (
    ObjectForecast,
    TimeSeriesForecast,
    _linear_extrapolation,
    _prophet_forecast,
    forecast_object_metrics,
)


# ─────────────────────────────────────────────────────────────────────
# Counterfactual
# ─────────────────────────────────────────────────────────────────────
def _make_features(
    battery: float = 30.0, power: bool = False, gen: bool = False
) -> ScoreFeatures:
    return ScoreFeatures(
        battery_pct=battery,
        battery_est_hours=2.0,
        temp_c=22.0,
        co2_ppm=800.0,
        occupancy_ratio=0.5,
        criticality=4,
        has_generator=gen,
        has_starlink=False,
        power_on=power,
        internet_on=False,
        signal=2,
        humidity_pct=50.0,
        generator_on=False,
    )


def test_counterfactual_generator_intervention():
    """Generator intervention покращує score."""
    base = _make_features(battery=15.0, power=False, gen=False)
    intervention = InterventionSpec(
        object_id="obj-1",
        intervention_type="generator",
        effect_battery_pct=100.0,
    )
    result = analyze_intervention("Test Shelter", base, intervention)
    assert result.after_score > result.before_score
    assert result.will_rescue is True


def test_counterfactual_evacuation():
    """Evacuation intervention зменшує occupancy."""
    base = _make_features(battery=50.0, power=True)
    base_high_occ = ScoreFeatures(**{**base.model_dump(), "occupancy_ratio": 1.5})
    intervention = InterventionSpec(
        object_id="obj-1",
        intervention_type="evacuation",
        effect_occupancy_relief=0.5,
    )
    result = analyze_intervention("Test", base_high_occ, intervention)
    # Після евакуації occupancy_ratio має бути ~0.75
    assert result.after_score >= result.before_score


def test_counterfactual_run_analysis():
    """run_counterfactual повертає правильну структуру."""
    objs = [
        ("obj-1", "Test 1", _make_features(battery=20.0, power=False)),
        ("obj-2", "Test 2", _make_features(battery=80.0, power=True)),
    ]
    interventions = [
        InterventionSpec(object_id="obj-1", intervention_type="generator"),
    ]
    analysis = run_counterfactual(objs, interventions)
    assert isinstance(analysis, CounterfactualAnalysis)
    assert (
        analysis.post_intervention_avg_score > analysis.baseline_avg_score
        or analysis.critical_reduction >= 0
    )
    assert (
        "Strongly" in analysis.recommendation
        or "Marginal" in analysis.recommendation
        or "No" in analysis.recommendation
    )


def test_counterfactual_empty_data():
    """Порожні дані → trivial analysis."""
    analysis = run_counterfactual([], [])
    assert analysis.baseline_avg_score == 0.0
    assert analysis.recommendation == "No data"


def test_counterfactual_no_intervention_means_no_change():
    """Без interventions — score_improvement = 0."""
    objs = [("obj-1", "Test", _make_features())]
    analysis = run_counterfactual(objs, [])
    assert analysis.score_improvement == 0.0
    assert analysis.critical_reduction == 0


# ─────────────────────────────────────────────────────────────────────
# Time-series forecast
# ─────────────────────────────────────────────────────────────────────
def test_linear_extrapolation_basic():
    """Linear extrapolation працює з мінімальними даними."""
    points = [(time.time() - 600, 80.0), (time.time(), 60.0)]
    fc = _linear_extrapolation(points, horizon_min=120)
    assert fc.method == "linear"
    assert fc.trend_direction == "decreasing"


def test_linear_extrapolation_single_point():
    """Один point → constant forecast."""
    points = [(time.time(), 50.0)]
    fc = _linear_extrapolation(points, horizon_min=60)
    assert fc.method == "constant"
    assert fc.current_value == 50.0


def test_prophet_forecast_with_sufficient_data():
    """Prophet forecast з 50+ points."""
    rng = np.random.RandomState(42)
    n = 80
    base_ts = time.time() - n * 600
    points = [(base_ts + i * 600, 80.0 - i * 0.5 + rng.normal(0, 1)) for i in range(n)]
    fc = _prophet_forecast("test", points, horizon_min=60, clip_range=(0, 100))
    assert fc.method in ("prophet", "linear")  # Prophet може впасти, тоді fallback
    if fc.method == "prophet":
        assert 0 <= fc.predicted_value <= 100
        assert fc.confidence > 0.5


def test_forecast_object_metrics_all_signals():
    """ObjectForecast повертає всі компоненти."""
    rng = np.random.RandomState(0)
    n = 100
    base_ts = time.time() - n * 300
    battery = [(base_ts + i * 300, 90.0 - i * 0.5) for i in range(n)]
    co2 = [(base_ts + i * 300, 500.0 + i * 2) for i in range(n)]
    occ = [(base_ts + i * 300, 50.0 + i * 0.5) for i in range(n)]
    forecast = forecast_object_metrics("obj-1", battery, co2, occ, horizon_min=120)
    assert forecast.object_id == "obj-1"
    assert forecast.battery_forecast is not None
    assert forecast.co2_forecast is not None
    assert forecast.occupancy_forecast is not None


def test_forecast_object_metrics_empty_warnings():
    """Порожні history lists → warnings."""
    forecast = forecast_object_metrics("obj-empty", [], [], [])
    assert len(forecast.warnings) == 3


# ─────────────────────────────────────────────────────────────────────
# Root Cause Analysis
# ─────────────────────────────────────────────────────────────────────
def test_rca_battery_depleted():
    """RCA: battery < 10% → battery_depleted."""
    from app.ml.monitoring.anomaly import AnomalyScore

    analyzer = RootCauseAnalyzer()
    anomaly = AnomalyScore(
        object_id="obj-1",
        timestamp=time.time(),
        score=-0.3,
        is_anomaly=True,
        feature_values={"battery_pct": 5.0, "co2_ppm": 500.0, "occupancy_ratio": 0.5},
    )
    z_scores = {"battery_pct": -5.0, "co2_ppm": 0.1, "occupancy_ratio": 0.0}
    analysis = analyzer.analyze(anomaly, anomaly.feature_values, z_scores)
    assert analysis.primary_cause == "battery_depleted"
    assert any(h.cause == "battery_depleted" for h in analysis.root_causes)


def test_rca_co2_leak():
    """RCA: CO2 > 2000 → co2_leak hypothesis."""
    from app.ml.monitoring.anomaly import AnomalyScore

    analyzer = RootCauseAnalyzer()
    anomaly = AnomalyScore(
        object_id="obj-1",
        timestamp=time.time(),
        score=-0.4,
        is_anomaly=True,
        feature_values={"battery_pct": 50.0, "co2_ppm": 2500.0, "occupancy_ratio": 0.5},
    )
    analysis = analyzer.analyze(anomaly, anomaly.feature_values, {})
    assert any(
        h.cause == "co2_leak_or_ventilation_failure" for h in analysis.root_causes
    )


def test_rca_occupancy_overload():
    """RCA: occupancy > 1.3 → overload hypothesis."""
    from app.ml.monitoring.anomaly import AnomalyScore

    analyzer = RootCauseAnalyzer()
    anomaly = AnomalyScore(
        object_id="obj-1",
        timestamp=time.time(),
        score=-0.4,
        is_anomaly=True,
        feature_values={"battery_pct": 50.0, "co2_ppm": 500.0, "occupancy_ratio": 1.5},
    )
    analysis = analyzer.analyze(anomaly, anomaly.feature_values, {})
    assert any(h.cause == "occupancy_overload" for h in analysis.root_causes)


def test_rca_power_loss_no_backup():
    """RCA: power off + no generator → power_loss_no_backup."""
    from app.ml.monitoring.anomaly import AnomalyScore

    analyzer = RootCauseAnalyzer()
    anomaly = AnomalyScore(
        object_id="obj-1",
        timestamp=time.time(),
        score=-0.5,
        is_anomaly=True,
        feature_values={
            "battery_pct": 30.0,
            "co2_ppm": 500.0,
            "occupancy_ratio": 0.3,
            "power_on": 0.0,
            "has_generator": 0.0,
        },
    )
    analysis = analyzer.analyze(anomaly, anomaly.feature_values, {})
    assert any(h.cause == "power_loss_no_backup" for h in analysis.root_causes)


# ─────────────────────────────────────────────────────────────────────
# Model Cards
# ─────────────────────────────────────────────────────────────────────
def test_model_cards_registry():
    """Усі основні моделі мають cards."""
    assert "score_model" in MODEL_CARDS
    assert "ranker_model" in MODEL_CARDS
    assert "anomaly_detector" in MODEL_CARDS
    assert "drift_detector" in MODEL_CARDS


def test_model_card_get():
    """get_model_card повертає валідний card."""
    card = get_model_card("score_model")
    assert card is not None
    assert isinstance(card, ModelCard)
    assert card.model_type == "regression"
    assert "R^2" in str(card.metrics) or "r2" in card.metrics


def test_model_card_to_dict():
    """to_dict серіалізується."""
    card = get_model_card("score_model")
    d = card.to_dict()
    assert "model_name" in d
    assert "intended_use" in d
    assert "limitations" in d
    assert "ethical_considerations" in d
    assert isinstance(d["features"], list)
    assert len(d["features"]) > 5


def test_list_model_cards():
    """list_model_cards повертає всі ключі."""
    cards = list_model_cards()
    assert len(cards) == len(MODEL_CARDS)
    assert "score_model" in cards


def test_model_card_for_unknown_returns_none():
    """get_model_card з unknown повертає None."""
    assert get_model_card("nonexistent_model") is None
