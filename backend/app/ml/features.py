"""
Feature schema and engineering for ResQHub ML models.

Це ЄДИНЕ місце, де визначається список фіч для score-моделі.
Усі оновлення фіч мають супроводжуватись bump MODEL_VERSION у store.py
і перетренуванням через `python -m app.ml.train`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

FEATURE_NAMES: tuple[str, ...] = (
    "battery_pct",
    "battery_est_hours",
    "temp_c",
    "co2_ppm",
    "occupancy_ratio",
    "criticality",
    "has_generator",
    "has_starlink",
    "power_on",
    "internet_on",
    "signal",
    "humidity_pct",
    "generator_on",
)


class ScoreFeatures(BaseModel):
    """Validated input feature vector for the score model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    battery_pct: float = Field(ge=0.0, le=100.0)
    battery_est_hours: float = Field(ge=0.0, le=168.0)
    temp_c: float = Field(ge=-30.0, le=60.0)
    co2_ppm: float = Field(ge=300.0, le=5000.0)
    occupancy_ratio: float = Field(ge=0.0, le=2.0)
    criticality: int = Field(ge=1, le=5)
    has_generator: bool
    has_starlink: bool
    power_on: bool
    internet_on: bool
    signal: int = Field(ge=0, le=4)
    humidity_pct: float = Field(ge=0.0, le=100.0)
    generator_on: bool

    def to_array(self) -> np.ndarray:
        """Повертає numpy-вектор у порядку FEATURE_NAMES."""
        return np.array(
            [
                [
                    self.battery_pct,
                    self.battery_est_hours,
                    self.temp_c,
                    self.co2_ppm,
                    self.occupancy_ratio,
                    float(self.criticality),
                    float(self.has_generator),
                    float(self.has_starlink),
                    float(self.power_on),
                    float(self.internet_on),
                    float(self.signal),
                    self.humidity_pct,
                    float(self.generator_on),
                ]
            ],
            dtype=np.float64,
        )


@dataclass(frozen=True)
class FeatureBundle:
    """Контейнер для масивів ознак — використовується в dataset/train."""

    X: np.ndarray
    y: np.ndarray
    y_status: np.ndarray
    feature_names: tuple[str, ...] = FEATURE_NAMES

    @property
    def n_samples(self) -> int:
        return int(self.X.shape[0])

    def to_arrays(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        return self.X, self.y, self.y_status


def stack_features(records: Iterable[ScoreFeatures]) -> np.ndarray:
    """Перетворює список ScoreFeatures у 2D numpy-масив."""
    return np.vstack([r.to_array()[0] for r in records]).astype(np.float64)


def feature_names() -> list[str]:
    return list(FEATURE_NAMES)
