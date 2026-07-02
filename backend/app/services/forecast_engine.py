"""
Forecast Engine — прогноз часу до критичного стану об'єкта.

Використовує фізичну модель: slope = -battery_pct / battery_est_hours,
time_to_critical = (battery_pct - CRITICAL_BATTERY_PCT) / 100 * battery_est_hours.

Це надає стабільні реалістичні ttc значення (60-120 хв під час блекауту),
незалежно від шуму лінійної регресії на малих інтервалах симулятора.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.score_engine import CRITICAL_BATTERY_PCT


@dataclass(frozen=True)
class TelemetryPoint:
    ts: float
    battery_pct: float
    power_on: bool
    battery_est_hours: float = 24.0
    generator_on: bool = False

    @property
    def powered(self) -> bool:
        """Об'єкт має живлення: мережа АБО працюючий генератор."""
        return self.power_on or self.generator_on


@dataclass(frozen=True)
class ForecastResult:
    """Прогноз у хвилинах до критичного стану.

    Attributes:
        time_to_critical_min: None = нескоро / не прогнозується
        slope_pct_per_min: швидкість розряду (негативна) у %/хв
        confidence: 0-1, довіра до прогнозу
    """

    time_to_critical_min: float | None
    slope_pct_per_min: float
    confidence: float


def forecast_time_to_critical(
    points: list[TelemetryPoint],
    window_size: int = 12,
) -> ForecastResult:
    """Прогнозування часу до критичного стану батареї (фізична модель).

    Логіка:
      1. Якщо остання точка power_on=True та prev також power_on — стабільно, None.
      2. Якщо остання power_on=False (розряджається):
           slope_pct_per_min = -(battery_pct / max(battery_est_hours, 0.1)) / 60
           delta_min = (battery_pct - CRITICAL_BATTERY_PCT) / 100 * battery_est_hours * 60
      3. Якщо жодної discharging точки — None.
    """
    if len(points) < 1:
        return ForecastResult(
            time_to_critical_min=None, slope_pct_per_min=0.0, confidence=0.0
        )

    recent = points[-window_size:]

    # Якщо живлення стабільне весь час (мережа або генератор) — заряд не падає
    if all(p.powered for p in recent):
        return ForecastResult(
            time_to_critical_min=None, slope_pct_per_min=0.0, confidence=1.0
        )

    # Беремо останню точку (актуальний стан)
    last = recent[-1]
    if last.powered:
        # Живлення відновилось (мережа чи генератор), прогноз не потрібен
        return ForecastResult(
            time_to_critical_min=None, slope_pct_per_min=0.0, confidence=0.7
        )

    # Розряджається: фізична модель
    est_hours = max(last.battery_est_hours, 0.05)
    if last.battery_pct <= CRITICAL_BATTERY_PCT:
        return ForecastResult(
            time_to_critical_min=0.0,
            slope_pct_per_min=-last.battery_pct / (est_hours * 60),
            confidence=0.95,
        )

    slope_per_min = -(last.battery_pct / (est_hours * 60.0))
    delta_pct = last.battery_pct - CRITICAL_BATTERY_PCT
    delta_min = (delta_pct / 100.0) * est_hours * 60.0

    # Довіра: більше discharging точок = вища довіра
    discharging_count = sum(1 for p in recent if not p.powered)
    confidence = min(1.0, discharging_count / max(window_size, 4))

    return ForecastResult(
        time_to_critical_min=round(delta_min, 1),
        slope_pct_per_min=round(slope_per_min, 4),
        confidence=round(confidence, 2),
    )
