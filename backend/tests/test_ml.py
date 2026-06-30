"""
Unit tests for the ML pipeline.

Запуск:
    cd backend
    pytest tests/ -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Додаємо backend до PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.ml.dataset import (
    generate_dataset,
    int_to_status,
    status_to_int,
)
from app.ml.features import FEATURE_NAMES, ScoreFeatures
from app.ml.routing_ml import (
    build_ranker_features,
    haversine_km,
)


def test_dataset_shape_and_diversity():
    """Датасет має правильний shape і різноманітні сценарії."""
    bundle = generate_dataset(n_samples=500)
    assert bundle.X.shape == (500, len(FEATURE_NAMES))
    assert bundle.y.shape == (500,)
    # Має бути хоча б один приклад кожного статусу
    statuses = set(bundle.y_status)
    assert "STABLE" in statuses or "WARNING" in statuses or "CRITICAL" in statuses


def test_dataset_feature_ranges():
    """Усі фічі в межах валідних діапазонів."""
    bundle = generate_dataset(n_samples=200)
    X = bundle.X
    # battery_pct in [0, 100]
    assert (X[:, 0] >= 0).all() and (X[:, 0] <= 100).all()
    # criticality in [1, 5]
    assert (X[:, 5] >= 1).all() and (X[:, 5] <= 5).all()
    # signal in [0, 4]
    assert (X[:, 10] >= 0).all() and (X[:, 10] <= 4).all()


def test_score_features_to_array():
    """ScoreFeatures коректно серіалізується в numpy array."""
    feats = ScoreFeatures(
        battery_pct=50.0,
        battery_est_hours=2.0,
        temp_c=22.0,
        co2_ppm=600.0,
        occupancy_ratio=0.5,
        criticality=3,
        has_generator=True,
        has_starlink=False,
        power_on=True,
        internet_on=True,
        signal=4,
        humidity_pct=50.0,
        generator_on=False,
    )
    arr = feats.to_array()
    assert arr.shape == (1, len(FEATURE_NAMES))
    assert arr[0, 0] == 50.0
    assert arr[0, 6] == 1.0  # has_generator
    assert arr[0, 7] == 0.0  # has_starlink


def test_score_features_validation_rejects_invalid():
    """Pydantic має відкидати невалідні значення."""
    with pytest.raises(Exception):
        ScoreFeatures(
            battery_pct=150.0,  # > 100
            battery_est_hours=2.0,
            temp_c=22.0,
            co2_ppm=600.0,
            occupancy_ratio=0.5,
            criticality=3,
            has_generator=True,
            has_starlink=False,
            power_on=True,
            internet_on=True,
            signal=4,
            humidity_pct=50.0,
            generator_on=False,
        )


def test_haversine_known_distance():
    """Haversine дає правильну відстань для відомих міст."""
    # Київ - Львів ≈ 470 км
    kiev_lat, kiev_lon = 50.4501, 30.5234
    lviv_lat, lviv_lon = 49.8397, 24.0297
    dist = haversine_km(kiev_lat, kiev_lon, lviv_lat, lviv_lon)
    assert 460 < dist < 480


def test_haversine_zero_distance():
    """Haversine для однакових точок = 0."""
    dist = haversine_km(50.0, 28.0, 50.0, 28.0)
    assert dist == 0.0


def test_ranker_features_shape():
    """Ranker features має правильний shape."""
    feats = build_ranker_features(
        current_score=70.0,
        time_to_critical_min=45.0,
        criticality=4,
        occupancy=80,
        capacity=100,
        battery_pct=60.0,
        has_generator=False,
        has_starlink=True,
        power_on=False,
    )
    assert feats.shape == (1, 10)
    # ttc < 60 → status_severity == 1.0
    assert feats[0, 9] == 1.0


def test_ranker_features_missing_ttc():
    """Якщо ttc=None → ttc_missing=1.0, time_to_critical=999."""
    feats = build_ranker_features(
        current_score=90.0,
        time_to_critical_min=None,
        criticality=3,
        occupancy=10,
        capacity=100,
        battery_pct=95.0,
        has_generator=True,
        has_starlink=False,
        power_on=True,
    )
    assert feats[0, 1] == 999.0  # ttc placeholder
    assert feats[0, 8] == 1.0  # ttc_missing = True (time_to_critical=None)


def test_status_roundtrip():
    """status_to_int ↔ int_to_status roundtrip."""
    for s in ["STABLE", "WARNING", "CRITICAL"]:
        assert int_to_status(status_to_int(s)) == s


def test_inference_loads_model_after_training(tmp_path):
    """Після тренування inference може завантажити артефакт."""
    from app.ml.store import (
        ARTIFACTS_DIR,
        SCORE_MODEL_VERSION,
        save_artifact,
        load_artifact,
    )

    # Зберігаємо фейковий артефакт
    name = f"score_model_{SCORE_MODEL_VERSION}"
    fake_payload = {"regressor": "fake", "feature_names": list(FEATURE_NAMES)}
    save_artifact(name, fake_payload)

    try:
        loaded = load_artifact(name)
        assert loaded["regressor"] == "fake"
    finally:
        # Cleanup
        path = ARTIFACTS_DIR / f"{name}.joblib"
        if path.exists():
            path.unlink()
