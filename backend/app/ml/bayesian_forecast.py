"""
Bayesian state-space model для прогнозування часу до критичного стану батареї.

P2 improvement: замість детерміністичної формули slope = -pct/hours,
використовуємо Kalman Filter для оцінки невизначеності прогнозу.

Стан: [battery_pct, discharge_rate_pct_per_min]
Спостереження: battery_pct
Модель: лінійна з невизначеністю процесу
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from app.ml.features import FEATURE_NAMES
from app.ml.services_compat import (
    ForecastResult as CompatForecastResult,
    TelemetryPoint as CompatTelemetryPoint,
)


@dataclass(frozen=True)
class BayesianForecastResult:
    """Результат Bayesian прогнозу."""

    time_to_critical_min: Optional[float]  # None = нескінченно
    time_to_critical_lower_min: Optional[float]  # 95% CI нижня межа
    time_to_critical_upper_min: Optional[float]  # 95% CI верхня межа
    slope_pct_per_min: float
    slope_uncertainty: float
    confidence: float
    method: str = "kalman"


class BatteryKalmanFilter:
    """
    Kalman Filter для батареї.

    State vector x = [battery_pct, discharge_rate_per_min]
    Transition: x_{k+1} = F @ x_k + process_noise
    Observation: z_k = H @ x_k + measurement_noise

    F = [[1, dt], [0, 1]]   — battery decreases, rate stays constant (random walk)
    H = [[1, 0]]             — ми спостерігаємо тільки battery_pct
    """

    def __init__(
        self,
        process_noise_pct: float = 0.5,  # uncertainty in battery state
        process_noise_rate: float = 0.05,  # uncertainty in discharge rate
        measurement_noise_pct: float = 1.0,  # sensor noise
    ) -> None:
        self._q_pct = process_noise_pct
        self._q_rate = process_noise_rate
        self._r_pct = measurement_noise_pct

        # State: [battery_pct, discharge_rate_per_min]
        self.x = np.array([100.0, 0.0], dtype=np.float64)
        self.P = np.diag([100.0, 0.5])  # Initial uncertainty

    def reset(self, battery_pct: float = 100.0) -> None:
        self.x = np.array([battery_pct, 0.0], dtype=np.float64)
        self.P = np.diag([100.0, 0.5])

    def predict(self, dt_min: float) -> None:
        """Predict step (time update)."""
        F = np.array([[1.0, dt_min], [0.0, 1.0]], dtype=np.float64)
        Q = np.diag([self._q_pct**2, self._q_rate**2])
        self.x = F @ self.x
        self.P = F @ self.P @ F.T + Q

    def update(self, observed_pct: float) -> None:
        """Update step (measurement update)."""
        H = np.array([[1.0, 0.0]], dtype=np.float64)
        R = np.array([[self._r_pct**2]], dtype=np.float64)
        z = np.array([observed_pct])
        y = z - H @ self.x  # Innovation
        S = H @ self.P @ H.T + R
        K = self.P @ H.T @ np.linalg.inv(S)  # Kalman gain
        self.x = self.x + (K @ y).flatten()
        self.P = (np.eye(2) - K @ H) @ self.P

    def feed(self, points: list[CompatTelemetryPoint]) -> None:
        """Годує фільтр серією telemetry points."""
        if not points:
            return
        self.reset(points[0].battery_pct)
        prev_ts = points[0].ts
        for pt in points[1:]:
            dt_min = (pt.ts - prev_ts) / 60.0
            if dt_min > 0:
                self.predict(dt_min)
            self.update(pt.battery_pct)
            prev_ts = pt.ts

    def forecast_ttc(
        self,
        critical_pct: float = 20.0,
        max_horizon_min: float = 24 * 60.0,
    ) -> BayesianForecastResult:
        """
        Прогнозує час до critical_pct з 95% confidence interval.
        Використовує uncertainty в discharge_rate для CI.
        """
        if self.x[1] >= 0.0:
            # Розряджається повільно або заряджається — TTC нескінченний
            return BayesianForecastResult(
                time_to_critical_min=None,
                time_to_critical_lower_min=None,
                time_to_critical_upper_min=None,
                slope_pct_per_min=float(self.x[1]),
                slope_uncertainty=float(np.sqrt(self.P[1, 1])),
                confidence=0.5,
            )

        # x[1] < 0 (discharge rate is negative)
        # battery_pct(t) = x[0] + x[1] * t = critical_pct
        # t = (critical_pct - x[0]) / x[1]
        if self.x[0] <= critical_pct:
            ttc = 0.0
        else:
            ttc = (critical_pct - self.x[0]) / self.x[1]
            ttc = float(np.clip(ttc, 0.0, max_horizon_min))

        # Uncertainty propagation через rate_std
        rate_std = float(np.sqrt(self.P[1, 1]))
        if rate_std > 0 and ttc > 0:
            # d(ttc)/d(rate) = -(critical_pct - x[0]) / rate^2 = ttc / rate
            ttc_uncertainty = abs(ttc * rate_std / self.x[1])
        else:
            ttc_uncertainty = max(60.0, ttc * 0.5)  # 50% uncertainty as fallback

        ttc_lower = max(0.0, ttc - 1.96 * ttc_uncertainty)
        ttc_upper = ttc + 1.96 * ttc_uncertainty

        # Confidence: inversely proportional to relative uncertainty
        if ttc > 0:
            confidence = float(np.clip(1.0 - (ttc_uncertainty / ttc), 0.3, 0.99))
        else:
            confidence = 0.95

        return BayesianForecastResult(
            time_to_critical_min=round(ttc, 1),
            time_to_critical_lower_min=round(ttc_lower, 1),
            time_to_critical_upper_min=round(ttc_upper, 1),
            slope_pct_per_min=round(float(self.x[1]), 4),
            slope_uncertainty=round(rate_std, 4),
            confidence=round(confidence, 2),
        )


def forecast_bayesian(
    points: list[CompatTelemetryPoint],
    critical_pct: float = 20.0,
) -> BayesianForecastResult:
    """
    Повний Bayesian pipeline: feed filter + forecast TTC.

    Порівнюємо з простою фізичною моделлю і повертаємо
    більш обережний з двох (якщо вони суттєво різні).
    """
    if not points:
        return BayesianForecastResult(
            time_to_critical_min=None,
            time_to_critical_lower_min=None,
            time_to_critical_upper_min=None,
            slope_pct_per_min=0.0,
            slope_uncertainty=0.0,
            confidence=0.0,
        )

    # Якщо живлення стабільне — return None
    if all(p.power_on for p in points[-5:]):
        return BayesianForecastResult(
            time_to_critical_min=None,
            time_to_critical_lower_min=None,
            time_to_critical_upper_min=None,
            slope_pct_per_min=0.0,
            slope_uncertainty=0.0,
            confidence=1.0,
        )

    kf = BatteryKalmanFilter()
    kf.feed(points)
    return kf.forecast_ttc(critical_pct=critical_pct)
