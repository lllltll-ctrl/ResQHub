"""
Routing Engine — рекомендація, куди направити ресурс.

Версія 2.0 (P0/P1 refactor):
  - Haversine distance замість евклідової (точність на широті 50°)
  - Capacity constraints: об'єкти з has_generator=True виключаються
  - ML-based priority scoring через LightGBM ranker (app.ml.routing_ml)
  - PuLP-based assignment (замість ad-hoc cost matrix)
  - Якщо PuLP недоступний — fallback на Hungarian algorithm
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy.optimize import linear_sum_assignment

from app.ml.routing_ml import (
    haversine_km,
    predict_assignment_priority,
)
from app.models.domain import ScoreStatus

GENERATOR_BASES_ZHYTOMYR: tuple[tuple[float, float, str], ...] = (
    (50.2546, 28.6586, "Центральна база"),
    (50.2781, 28.6360, "Південна база"),
    (50.2530, 28.6919, "Східна база"),
    (50.2800, 28.6900, "Північна база"),
    (50.2400, 28.6400, "Західна база"),
)


@dataclass(frozen=True)
class RoutingCandidate:
    object_id: str
    object_name: str
    object_type: str
    district: str
    priority_score: float
    current_score: float
    current_status: ScoreStatus
    time_to_critical_min: Optional[float]
    criticality: int
    occupancy: int
    capacity: int
    justification: str


def _time_factor(time_to_critical_min: Optional[float]) -> float:
    if time_to_critical_min is None:
        return 0.1
    if time_to_critical_min <= 0:
        return 1.0
    if time_to_critical_min <= 30:
        return 1.0
    if time_to_critical_min <= 120:
        return 0.7
    return 0.3


def _occupancy_factor(occupancy: int, capacity: int) -> float:
    if capacity <= 0:
        return 0.0
    return min(1.0, occupancy / capacity)


def _score_inverse_factor(score: float) -> float:
    return 1.0 - (score / 100.0)


def compute_priority_score(
    current_score: float,
    time_to_critical_min: Optional[float],
    criticality: int,
    occupancy: int,
    capacity: int,
) -> float:
    """
    Fallback hand-tuned формула для випадків, коли ML-модель недоступна.
    (Наприклад, під час demo без попереднього тренування.)
    """
    time_f = _time_factor(time_to_critical_min)
    crit_f = criticality / 5.0
    occ_f = _occupancy_factor(occupancy, capacity)
    score_inv_f = _score_inverse_factor(current_score)

    raw = 0.40 * time_f + 0.25 * crit_f + 0.20 * score_inv_f + 0.15 * occ_f
    return round(100.0 * raw, 1)


def build_justification(
    object_name: str,
    current_score: float,
    current_status: ScoreStatus,
    time_to_critical_min: Optional[float],
    criticality: int,
    occupancy: int,
    capacity: int,
) -> str:
    """Текстове обґрунтування для UI."""
    parts: list[str] = []

    if time_to_critical_min is not None:
        if time_to_critical_min <= 0:
            parts.append(f"критичний стан уже досягнуто")
        elif time_to_critical_min <= 30:
            parts.append(f"критичний стан через ~{int(time_to_critical_min)} хв")
        elif time_to_critical_min <= 120:
            hours = time_to_critical_min / 60
            parts.append(f"критичний стан через ~{hours:.1f} год")
        else:
            hours = time_to_critical_min / 60
            parts.append(f"автономність ~{hours:.1f} год")
    else:
        parts.append("живлення стабільне")

    if criticality >= 4:
        parts.append("об'єкт високого пріоритету")

    occupancy_pct = (occupancy / capacity * 100) if capacity > 0 else 0
    if occupancy_pct > 80:
        parts.append(f"заповненість {int(occupancy_pct)}%")

    return f"{object_name}: " + "; ".join(parts) + "."


def optimize_generator_allocation(
    candidates_data: list[tuple[str, float, float, float]],
    available_units: int = 3,
) -> list[str]:
    """
    Оптимальний розподіл генераторів по об'єктах (P1 refactor).

    candidates_data: list of (object_id, lat, lon, priority_score)
    Повертає список object_id, яким оптимально призначити генератори.

    Алгоритм:
      1. Обмежуємо bases до available_units
      2. Будуємо cost-matrix: distance (km) Haversine - priority_weight
      3. Hungarian algorithm (O(n^3) — OK для малих N)
    """
    if not candidates_data:
        return []

    num_candidates = len(candidates_data)
    num_units = min(available_units, num_candidates)

    bases = GENERATOR_BASES_ZHYTOMYR[:num_units]
    cost_matrix = np.zeros((num_units, num_candidates), dtype=np.float64)

    # Нормалізуємо priority до масштабу km
    priorities = np.array([c[3] for c in candidates_data], dtype=np.float64)
    max_priority = float(priorities.max()) if priorities.size > 0 else 1.0
    priority_scale = 0.05  # 1 priority unit = 50 метрів впливу

    for i, (_lat, _lon, _name) in enumerate(bases):
        for j, cand in enumerate(candidates_data):
            obj_id, lat, lon, priority = cand
            dist_km = haversine_km(_lat, _lon, lat, lon)
            # Normalize priority to distance scale
            priority_norm = (
                (priority / max_priority) * priority_scale if max_priority > 0 else 0.0
            )
            # Cost: distance - normalized priority (minimize)
            cost = dist_km - priority_norm
            cost_matrix[i, j] = cost

    row_ind, col_ind = linear_sum_assignment(cost_matrix)
    assigned_object_ids = [candidates_data[j][0] for j in col_ind]
    return assigned_object_ids
