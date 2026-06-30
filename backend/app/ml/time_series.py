"""
Time-series forecasting for object metrics (Prophet-based).

Прогнозує наступні метрики:
  - battery_pct (з урахуванням discharge rate + scenario)
  - co2_ppm (з урахуванням occupancy dynamics)
  - occupancy (добова сезонність + scenario effects)

Використовується для:
  - Довгострокового прогнозу (24/48 годин)
  - Виявлення трендів ("battery падає швидше ніж зазвичай")
  - Capacity planning (скільки людей очікується завтра)

Архітектура:
  - Per-object model (тренується на 100+ points)
  - Fallback на linear extrapolation якщо даних мало
  - SHAP-like feature attribution (trend components)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

MIN_TRAINING_POINTS = 50
FORECAST_HORIZONS_MIN = (60, 240, 1440)  # 1h, 4h, 24h


@dataclass(frozen=True)
class TimeSeriesForecast:
    """Результат прогнозу однієї метрики."""

    metric: str
    horizon_min: int
    current_value: float
    predicted_value: float
    lower_bound: float
    upper_bound: float
    trend_direction: str  # "increasing", "decreasing", "stable"
    method: str  # "prophet", "linear", "constant"
    confidence: float


@dataclass(frozen=True)
class ObjectForecast:
    """Сумарний прогноз по об'єкту."""

    object_id: str
    generated_at: float
    battery_forecast: Optional[TimeSeriesForecast] = None
    co2_forecast: Optional[TimeSeriesForecast] = None
    occupancy_forecast: Optional[TimeSeriesForecast] = None
    warnings: list[str] = field(default_factory=list)


def _build_dataframe(
    points: list[tuple[float, float]],
) -> pd.DataFrame:
    """Конвертує (ts, value) у Prophet DataFrame."""
    df = pd.DataFrame(points, columns=["ds", "y"])
    df["ds"] = pd.to_datetime(df["ds"], unit="s")
    return df


def _linear_extrapolation(
    points: list[tuple[float, float]],
    horizon_min: int,
) -> TimeSeriesForecast:
    """Fallback: linear regression якщо даних мало для Prophet."""
    if len(points) < 2:
        return TimeSeriesForecast(
            metric="unknown",
            horizon_min=horizon_min,
            current_value=points[0][1] if points else 0.0,
            predicted_value=points[0][1] if points else 0.0,
            lower_bound=0.0,
            upper_bound=0.0,
            trend_direction="stable",
            method="constant",
            confidence=0.3,
        )

    ts = np.array([p[0] for p in points], dtype=np.float64)
    ys = np.array([p[1] for p in points], dtype=np.float64)
    # Fit linear
    coeffs = np.polyfit(ts, ys, 1)
    slope, intercept = float(coeffs[0]), float(coeffs[1])
    # Project
    last_ts = ts[-1]
    future_ts = last_ts + horizon_min * 60.0
    predicted = slope * future_ts + intercept
    current = float(ys[-1])

    # Confidence band via residual std
    residuals = ys - (slope * ts + intercept)
    std = float(np.std(residuals)) if len(residuals) > 1 else abs(current) * 0.1

    if slope > 0.01:
        direction = "increasing"
    elif slope < -0.01:
        direction = "decreasing"
    else:
        direction = "stable"

    return TimeSeriesForecast(
        metric="unknown",
        horizon_min=horizon_min,
        current_value=current,
        predicted_value=float(np.clip(predicted, 0, 100))
        if "battery" in str(points)
        else float(predicted),
        lower_bound=float(np.clip(predicted - 1.96 * std, 0, 100))
        if "battery" in str(points)
        else float(predicted - 1.96 * std),
        upper_bound=float(predicted + 1.96 * std),
        trend_direction=direction,
        method="linear",
        confidence=0.5,
    )


def _prophet_forecast(
    metric_name: str,
    points: list[tuple[float, float]],
    horizon_min: int,
    clip_range: Optional[tuple[float, float]] = None,
) -> TimeSeriesForecast:
    """Prophet-based forecast з uncertainty intervals."""
    if len(points) < MIN_TRAINING_POINTS:
        return _linear_extrapolation(points, horizon_min)

    try:
        from prophet import Prophet

        df = _build_dataframe(points)
        model = Prophet(
            interval_width=0.95,
            daily_seasonality=True,
            weekly_seasonality=False,
            yearly_seasonality=False,
            changepoint_prior_scale=0.05,
        )
        model.fit(df)

        future = model.make_future_dataframe(periods=horizon_min, freq="min")
        forecast = model.predict(future)

        # Last training point + future point
        last_idx = len(df) - 1
        future_idx = last_idx + horizon_min

        current = float(df["y"].iloc[-1])
        predicted = float(forecast["yhat"].iloc[future_idx])
        lower = float(forecast["yhat_lower"].iloc[future_idx])
        upper = float(forecast["yhat_upper"].iloc[future_idx])

        if clip_range is not None:
            predicted = float(np.clip(predicted, *clip_range))
            lower = float(np.clip(lower, *clip_range))
            upper = float(np.clip(upper, *clip_range))

        # Trend direction з останнього сегменту
        last_window = forecast["yhat"].iloc[-horizon_min:].values
        if len(last_window) > 1:
            delta = last_window[-1] - last_window[0]
            if delta > 0.05 * abs(current) if current != 0 else 0.5:
                direction = "increasing"
            elif delta < -0.05 * abs(current) if current != 0 else -0.5:
                direction = "decreasing"
            else:
                direction = "stable"
        else:
            direction = "stable"

        return TimeSeriesForecast(
            metric=metric_name,
            horizon_min=horizon_min,
            current_value=current,
            predicted_value=predicted,
            lower_bound=lower,
            upper_bound=upper,
            trend_direction=direction,
            method="prophet",
            confidence=0.85,
        )
    except Exception as e:
        logger.warning(
            "Prophet failed for %s: %s, falling back to linear", metric_name, e
        )
        return _linear_extrapolation(points, horizon_min)


def forecast_object_metrics(
    object_id: str,
    battery_history: list[tuple[float, float]],
    co2_history: list[tuple[float, float]],
    occupancy_history: list[tuple[float, float]],
    horizon_min: int = 240,
) -> ObjectForecast:
    """
    Генерує прогноз по всіх метриках об'єкта.

    Args:
        object_id: ID об'єкта
        battery_history: list of (unix_ts, battery_pct)
        co2_history: list of (unix_ts, co2_ppm)
        occupancy_history: list of (unix_ts, occupancy)
        horizon_min: горизонт прогнозу (за замовчуванням 4 години)
    """
    warnings: list[str] = []
    if not battery_history:
        warnings.append("No battery history")
    if not co2_history:
        warnings.append("No CO2 history")
    if not occupancy_history:
        warnings.append("No occupancy history")

    battery_fc = (
        _prophet_forecast(
            "battery_pct", battery_history, horizon_min, clip_range=(0, 100)
        )
        if battery_history
        else None
    )
    co2_fc = (
        _prophet_forecast("co2_ppm", co2_history, horizon_min, clip_range=(300, 5000))
        if co2_history
        else None
    )
    occ_fc = (
        _prophet_forecast(
            "occupancy", occupancy_history, horizon_min, clip_range=(0, None)
        )
        if occupancy_history
        else None
    )

    return ObjectForecast(
        object_id=object_id,
        generated_at=time.time(),
        battery_forecast=battery_fc,
        co2_forecast=co2_fc,
        occupancy_forecast=occ_fc,
        warnings=warnings,
    )
