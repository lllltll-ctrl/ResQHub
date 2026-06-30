"""
ML-based priority scoring for resource assignment.

Замінює hand-tuned зважену формулу з routing_engine.compute_priority_score
на LightGBM ranker (тренується у ml/train.py).

Додатково:
  - Haversine distance замість евклідової
  - Capacity constraints: об'єкт з has_generator=True не може бути кандидатом
  - Resource type-specific scoring
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

from app.ml.inference import _load_ranker, get_ranker_feature_names


RANKER_FEATURE_NAMES: tuple[str, ...] = (
    "current_score",
    "time_to_critical_min",
    "criticality",
    "occupancy_ratio",
    "battery_pct",
    "has_generator",
    "has_starlink",
    "power_on",
    "ttc_missing",
    "status_severity",
)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Відстань у кілометрах між двома точками (Haversine)."""
    r = 6371.0
    p = math.pi / 180.0
    a = (
        math.sin((lat2 - lat1) * p / 2.0) ** 2.0
        + math.cos(lat1 * p)
        * math.cos(lat2 * p)
        * math.sin((lon2 - lon1) * p / 2.0) ** 2.0
    )
    return 2.0 * r * math.asin(min(1.0, math.sqrt(a)))


def build_ranker_features(
    current_score: float,
    time_to_critical_min: Optional[float],
    criticality: int,
    occupancy: int,
    capacity: int,
    battery_pct: float,
    has_generator: bool,
    has_starlink: bool,
    power_on: bool,
) -> np.ndarray:
    """
    Будує 1D feature-vector для ranker-моделі.
    """
    occ_ratio = (occupancy / capacity) if capacity > 0 else 0.0
    # ttc_missing = True, коли ttc=None (стабільне живлення, прогноз не потрібен)
    ttc_missing = 1.0 if time_to_critical_min is None else 0.0
    if time_to_critical_min is None:
        time_to_critical_min = 999.0
    status_severity = 0.0
    if time_to_critical_min < 60:
        status_severity = 1.0
    if time_to_critical_min < 30:
        status_severity = 2.0

    return np.array(
        [
            current_score,
            time_to_critical_min,
            float(criticality),
            occ_ratio,
            battery_pct,
            float(has_generator),
            float(has_starlink),
            float(power_on),
            ttc_missing,
            status_severity,
        ],
        dtype=np.float64,
    ).reshape(1, -1)


def predict_assignment_priority(
    current_score: float,
    time_to_critical_min: Optional[float],
    criticality: int,
    occupancy: int,
    capacity: int,
    battery_pct: float,
    has_generator: bool,
    has_starlink: bool,
    power_on: bool,
) -> float:
    """
    Прогнозує priority_score (ranker-модель).
    Чим більше — тим вищий пріоритет для призначення ресурсу.
    """
    artifact = _load_ranker()
    model = artifact["model"]
    X = build_ranker_features(
        current_score=current_score,
        time_to_critical_min=time_to_critical_min,
        criticality=criticality,
        occupancy=occupancy,
        capacity=capacity,
        battery_pct=battery_pct,
        has_generator=has_generator,
        has_starlink=has_starlink,
        power_on=power_on,
    )
    raw = float(model.predict(X)[0])
    # Нормалізуємо до 0-100 (ranker raw output може бути від'ємним)
    return float(max(0.0, min(100.0, raw * 25.0 + 50.0)))


def rank_candidates(
    candidates: list[dict],
) -> list[dict]:
    """
    Сортує кандидатів за ML-прогнозом priority_score.
    `candidates` — список dict з полями:
        current_score, time_to_critical_min, criticality,
        occupancy, capacity, battery_pct, has_generator,
        has_starlink, power_on
    """
    if not candidates:
        return []

    X = np.vstack(
        [
            build_ranker_features(
                current_score=c["current_score"],
                time_to_critical_min=c.get("time_to_critical_min"),
                criticality=c["criticality"],
                occupancy=c["occupancy"],
                capacity=c["capacity"],
                battery_pct=c.get("battery_pct", 50.0),
                has_generator=c.get("has_generator", False),
                has_starlink=c.get("has_starlink", False),
                power_on=c.get("power_on", True),
            )[0]
            for c in candidates
        ]
    )
    artifact = _load_ranker()
    model = artifact["model"]
    raw_scores = model.predict(X)
    normalized = np.clip(raw_scores * 25.0 + 50.0, 0.0, 100.0)
    for c, s in zip(candidates, normalized):
        c["priority_score"] = round(float(s), 1)
    candidates.sort(key=lambda c: c["priority_score"], reverse=True)
    return candidates
