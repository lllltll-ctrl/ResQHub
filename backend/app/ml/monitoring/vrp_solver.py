"""
Vehicle Routing Problem (VRP) solver via PuLP.

Заміна Hungarian algorithm з P1:
  - Capacity constraints (генератор обслуговує обмежену кількість об'єктів)
  - Time windows (ETA кожного кандидата)
  - Multi-resource support (генератори, бригади, starlink)
  - Optimization-based: мінімізуємо total time/distance

Fallback на Hungarian, якщо PuLP недоступний.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

from app.ml.routing_ml import haversine_km

logger = logging.getLogger(__name__)

# Бази техніки у Житомирі: (lat, lon, name, capacity, speed_kmh)
RESOURCE_BASES = (
    {
        "name": "Центральна база",
        "lat": 50.2546,
        "lon": 28.6586,
        "capacity": 2,
        "speed_kmh": 40.0,
    },
    {
        "name": "Південна база",
        "lat": 50.2400,
        "lon": 28.6400,
        "capacity": 2,
        "speed_kmh": 35.0,
    },
    {
        "name": "Східна база",
        "lat": 50.2800,
        "lon": 28.6900,
        "capacity": 1,
        "speed_kmh": 30.0,
    },
    {
        "name": "Північна база",
        "lat": 50.2900,
        "lon": 28.6700,
        "capacity": 2,
        "speed_kmh": 38.0,
    },
    {
        "name": "Західна база",
        "lat": 50.2700,
        "lon": 28.6100,
        "capacity": 1,
        "speed_kmh": 32.0,
    },
)


@dataclass(frozen=True)
class VRPCandidate:
    """Один кандидат для VRP."""

    object_id: str
    lat: float
    lon: float
    priority_score: float
    time_to_critical_min: Optional[float]  # deadline (None = no urgency)
    demand: int = 1  # скільки одиниць техніки потрібно (зазвичай 1)


@dataclass(frozen=True)
class VRPAssignment:
    """Результат призначення."""

    object_id: str
    base_name: str
    eta_min: int
    travel_km: float
    is_covered: bool


def solve_vrp(
    candidates: list[VRPCandidate],
    resource_type: str = "GENERATOR",
    max_total_assignments: int = 5,
) -> list[VRPAssignment]:
    """
    Розв'язує Capacitated VRP з time windows через PuLP.

    Args:
        candidates: список кандидатів з координатами та priority
        resource_type: тип ресурсу (поки не впливає, тільки для логу)
        max_total_assignments: максимум призначень загалом

    Returns:
        Список VRPAssignment з призначеннями
    """
    if not candidates:
        return []

    try:
        return _solve_with_pulp(candidates, max_total_assignments)
    except ImportError:
        logger.warning("PuLP not available, falling back to greedy")
        return _solve_greedy(candidates, max_total_assignments)
    except Exception as e:
        logger.error("PuLP solver failed: %s, falling back to greedy", e)
        return _solve_greedy(candidates, max_total_assignments)


def _solve_with_pulp(
    candidates: list[VRPCandidate], max_total: int
) -> list[VRPAssignment]:
    """Розв'язання VRP через PuLP ILP."""
    import pulp

    bases = RESOURCE_BASES
    n_cand = len(candidates)
    n_bases = len(bases)

    # Pre-compute travel time (minutes) matrix
    time_matrix = np.zeros((n_bases, n_cand), dtype=np.float64)
    dist_matrix = np.zeros((n_bases, n_cand), dtype=np.float64)
    for i, base in enumerate(bases):
        for j, cand in enumerate(candidates):
            dist_km = haversine_km(base["lat"], base["lon"], cand.lat, cand.lon)
            dist_matrix[i, j] = dist_km
            # ETA = travel time + service time (15 min per stop)
            eta_min = (dist_km / base["speed_kmh"]) * 60.0 + 15.0
            time_matrix[i, j] = eta_min

    # ILP problem
    prob = pulp.LpProblem("VRP_Generator_Assignment", pulp.LpMaximize)

    # Decision vars: x[i][j] = 1 якщо base i обслуговує candidate j
    x = [
        [pulp.LpVariable(f"x_{i}_{j}", cat=pulp.LpBinary) for j in range(n_cand)]
        for i in range(n_bases)
    ]

    # Objective: maximize total priority_score - penalty * travel_time
    # We want high-priority objects covered, prefer closer bases
    priority_weight = 1.0
    time_penalty = 0.5

    objective_terms: list = []
    for i in range(n_bases):
        for j in range(n_cand):
            cand = candidates[j]
            # Reward for covering high-priority
            reward = priority_weight * cand.priority_score
            # Penalty for travel time
            penalty = time_penalty * time_matrix[i, j]
            objective_terms.append((reward - penalty) * x[i][j])

    prob += pulp.lpSum(objective_terms)

    # Constraint 1: кожен кандидат обслуговується не більше 1 раз
    for j in range(n_cand):
        prob += (
            pulp.lpSum(x[i][j] for i in range(n_bases)) <= 1,
            f"single_assignment_{j}",
        )

    # Constraint 2: capacity кожної бази
    for i, base in enumerate(bases):
        prob += (
            pulp.lpSum(x[i][j] for j in range(n_cand)) <= base["capacity"],
            f"capacity_{i}",
        )

    # Constraint 3: total assignments <= max_total
    prob += (
        pulp.lpSum(x[i][j] for i in range(n_bases) for j in range(n_cand)) <= max_total,
        "max_total",
    )

    # Constraint 4: time window — якщо ttc задано, ETA має бути < ttc
    for i in range(n_bases):
        for j, cand in enumerate(candidates):
            if cand.time_to_critical_min is not None and cand.time_to_critical_min > 0:
                # Якщо ETA > ttc, не призначати (з невеликим буфером)
                if time_matrix[i, j] > cand.time_to_critical_min * 0.9:
                    prob += x[i][j] == 0, f"time_window_{i}_{j}"

    # Розв'язуємо
    prob.solve(pulp.PULP_CBC_CMD(msg=0))

    if prob.status != 1:
        logger.warning(
            "PuLP solver did not find optimal solution (status=%s)", prob.status
        )

    # Збираємо результати
    assignments: list[VRPAssignment] = []
    for i, base in enumerate(bases):
        for j, cand in enumerate(candidates):
            if pulp.value(x[i][j]) > 0.5:
                assignments.append(
                    VRPAssignment(
                        object_id=cand.object_id,
                        base_name=base["name"],
                        eta_min=int(time_matrix[i, j]),
                        travel_km=float(dist_matrix[i, j]),
                        is_covered=True,
                    )
                )

    return assignments


def _solve_greedy(
    candidates: list[VRPCandidate], max_total: int
) -> list[VRPAssignment]:
    """
    Greedy fallback якщо PuLP недоступний.

    Сортує кандидатів за priority_score, призначає найближчу вільну базу
    з урахуванням capacity.
    """
    bases = list(RESOURCE_BASES)
    remaining_capacity = {b["name"]: b["capacity"] for b in bases}
    sorted_cands = sorted(candidates, key=lambda c: c.priority_score, reverse=True)

    assignments: list[VRPAssignment] = []
    for cand in sorted_cands:
        if len(assignments) >= max_total:
            break
        # Знайти найближчу базу з вільною capacity
        best_base = None
        best_eta = float("inf")
        best_dist = 0.0
        for base in bases:
            if remaining_capacity[base["name"]] <= 0:
                continue
            dist_km = haversine_km(base["lat"], base["lon"], cand.lat, cand.lon)
            eta_min = (dist_km / base["speed_kmh"]) * 60.0 + 15.0
            # Time window constraint
            if (
                cand.time_to_critical_min is not None
                and eta_min > cand.time_to_critical_min * 0.9
            ):
                continue
            if eta_min < best_eta:
                best_eta = eta_min
                best_base = base
                best_dist = dist_km
        if best_base is not None:
            remaining_capacity[best_base["name"]] -= 1
            assignments.append(
                VRPAssignment(
                    object_id=cand.object_id,
                    base_name=best_base["name"],
                    eta_min=int(best_eta),
                    travel_km=best_dist,
                    is_covered=True,
                )
            )
    return assignments
