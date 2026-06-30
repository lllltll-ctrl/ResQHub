"""
Unit tests for Bayesian state-space model (P2).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.ml.bayesian_forecast import (
    BayesianForecastResult,
    BatteryKalmanFilter,
    forecast_bayesian,
)
from app.services.forecast_engine import TelemetryPoint


def _make_linear_discharge(
    start_pct: float = 100.0,
    end_pct: float = 20.0,
    n_points: int = 10,
    interval_sec: float = 600.0,
) -> list[TelemetryPoint]:
    """Генерує серію з лінійним розрядом батареї."""
    points: list[TelemetryPoint] = []
    ts = time.time()
    for i in range(n_points):
        pct = start_pct + (end_pct - start_pct) * i / (n_points - 1)
        points.append(
            TelemetryPoint(ts=ts + i * interval_sec, battery_pct=pct, power_on=False)
        )
    return points


def test_kalman_filter_basic_tracking():
    """KF відстежує battery_pct."""
    kf = BatteryKalmanFilter()
    kf.reset(100.0)
    # Predict + update кілька разів
    for i in range(10):
        kf.predict(dt_min=10.0)
        observed = 100.0 - i * 5.0
        kf.update(observed)
    # battery_pct має бути близько 50%
    assert 40.0 < kf.x[0] < 60.0


def test_kalman_filter_estimates_negative_rate():
    """KF оцінює discharge rate як від'ємне число."""
    kf = BatteryKalmanFilter()
    kf.feed(
        _make_linear_discharge(start_pct=100, end_pct=20, n_points=15, interval_sec=300)
    )
    assert kf.x[1] < 0  # discharge rate is negative


def test_bayesian_forecast_with_discharge():
    """Bayesian forecast на серії з розрядом."""
    res = forecast_bayesian(
        _make_linear_discharge(start_pct=100, end_pct=40, n_points=10),
        critical_pct=20.0,
    )
    assert res.method == "kalman"
    # Battery на 40%, критичний поріг 20% → має бути додатний TTC
    assert res.time_to_critical_min is not None
    assert res.time_to_critical_min > 0
    # Confidence має бути розумним
    assert 0.3 <= res.confidence <= 0.99


def test_bayesian_forecast_confidence_interval():
    """CI має містити точкову оцінку TTC."""
    res = forecast_bayesian(
        _make_linear_discharge(start_pct=100, end_pct=50, n_points=8),
    )
    if res.time_to_critical_min is not None:
        # Lower bound < point < upper bound
        assert res.time_to_critical_lower_min is not None
        assert res.time_to_critical_upper_min is not None
        assert res.time_to_critical_lower_min <= res.time_to_critical_min
        assert res.time_to_critical_min <= res.time_to_critical_upper_min


def test_bayesian_forecast_stable_power():
    """Якщо power_on=True весь час — TTC=None."""
    points = [
        TelemetryPoint(ts=time.time() + i * 600, battery_pct=100.0, power_on=True)
        for i in range(10)
    ]
    res = forecast_bayesian(points)
    assert res.time_to_critical_min is None
    assert res.confidence == 1.0


def test_bayesian_forecast_empty():
    """Порожній список → нульова впевненість."""
    res = forecast_bayesian([])
    assert res.time_to_critical_min is None
    assert res.confidence == 0.0
    assert res.slope_pct_per_min == 0.0


def test_bayesian_forecast_battery_below_critical():
    """Якщо battery вже нижче critical — TTC=0."""
    points = _make_linear_discharge(start_pct=10.0, end_pct=5.0, n_points=5)
    res = forecast_bayesian(points, critical_pct=20.0)
    assert res.time_to_critical_min == 0.0
