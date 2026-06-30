"""
Tests for operator_briefing module.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.ml.features import ScoreFeatures
from app.ml.operator_briefing import (
    OperatorBriefing,
    generate_llm_briefing,
    generate_template_briefing,
)


def _make_features(
    battery: float = 30.0, co2: float = 800.0, occ: float = 0.5
) -> ScoreFeatures:
    return ScoreFeatures(
        battery_pct=battery,
        battery_est_hours=2.0,
        temp_c=22.0,
        co2_ppm=co2,
        occupancy_ratio=occ,
        criticality=4,
        has_generator=False,
        has_starlink=False,
        power_on=False,
        internet_on=False,
        signal=2,
        humidity_pct=50.0,
        generator_on=False,
    )


def test_template_briefing_critical():
    """Critical case генерує КРИТИЧНИЙ severity і action items."""
    feats = _make_features(battery=10.0, co2=2000.0, occ=1.3)
    b = generate_template_briefing(
        object_name="Test Hospital",
        object_type="HOSPITAL",
        features=feats,
        ml_score=15.0,
        ml_status="CRITICAL",
        ml_confidence=0.9,
        anomaly_detected=False,
        drift_detected=False,
        ttc_minutes=20.0,
    )
    assert b.severity == "CRITICAL"
    assert b.method == "template"
    assert "КРИТИЧНОМУ" in b.summary or "CRITICAL" in b.summary
    assert any("генератор" in a.lower() for a in b.recommended_actions)
    assert any("вентиляцію" in a.lower() for a in b.recommended_actions)
    assert any("розвантажити" in a.lower() for a in b.recommended_actions)


def test_template_briefing_warning():
    """Warning case генерує WARNING severity."""
    feats = _make_features(battery=50.0, co2=900.0, occ=0.7)
    b = generate_template_briefing(
        object_name="Test School",
        object_type="SCHOOL",
        features=feats,
        ml_score=55.0,
        ml_status="WARNING",
        ml_confidence=0.85,
        anomaly_detected=False,
        drift_detected=False,
    )
    assert b.severity == "WARNING"


def test_template_briefing_stable():
    """Stable case — немає критичних actions."""
    feats = _make_features(battery=95.0, co2=500.0, occ=0.3)
    b = generate_template_briefing(
        object_name="Test Shelter",
        object_type="SHELTER",
        features=feats,
        ml_score=95.0,
        ml_status="STABLE",
        ml_confidence=0.95,
        anomaly_detected=False,
        drift_detected=False,
    )
    assert b.severity == "STABLE"
    assert b.recommended_actions == ["Продовжувати моніторинг у штатному режимі"]


def test_template_briefing_with_anomaly():
    """Anomaly → додатковий action item."""
    feats = _make_features()
    b = generate_template_briefing(
        object_name="Test",
        object_type="SHELTER",
        features=feats,
        ml_score=50.0,
        ml_status="WARNING",
        ml_confidence=0.8,
        anomaly_detected=True,
        drift_detected=False,
    )
    assert any("аномалі" in a.lower() for a in b.recommended_actions)


def test_template_briefing_with_drift():
    """Drift → додатковий action item."""
    feats = _make_features()
    b = generate_template_briefing(
        object_name="Test",
        object_type="SHELTER",
        features=feats,
        ml_score=50.0,
        ml_status="WARNING",
        ml_confidence=0.8,
        anomaly_detected=False,
        drift_detected=True,
    )
    assert any("drift" in a.lower() for a in b.recommended_actions)


def test_template_briefing_low_confidence():
    """Low ML confidence → warning action."""
    feats = _make_features()
    b = generate_template_briefing(
        object_name="Test",
        object_type="SHELTER",
        features=feats,
        ml_score=50.0,
        ml_status="WARNING",
        ml_confidence=0.4,
        anomaly_detected=False,
        drift_detected=False,
    )
    assert any("невпевнена" in a.lower() for a in b.recommended_actions)


def test_template_briefing_key_factors():
    """key_factors містить top-3 SHAP."""
    feats = _make_features()
    b = generate_template_briefing(
        object_name="Test",
        object_type="SHELTER",
        features=feats,
        ml_score=50.0,
        ml_status="WARNING",
        ml_confidence=0.8,
        anomaly_detected=False,
        drift_detected=False,
    )
    assert len(b.key_factors) <= 3
    for name, val in b.key_factors:
        assert isinstance(name, str)
        assert isinstance(val, float)


def test_llm_briefing_falls_back_to_template():
    """Без OPENAI_API_KEY — fallback на template."""
    feats = _make_features()
    b = generate_llm_briefing(
        object_name="Test",
        object_type="SHELTER",
        features=feats,
        ml_score=50.0,
        ml_status="WARNING",
        ml_confidence=0.8,
        anomaly_detected=False,
        drift_detected=False,
    )
    assert b.method == "template"
