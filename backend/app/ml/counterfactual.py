"""
What-if / counterfactual analysis for routing decisions.

Дозволяє оператору побачити:
  - "Що буде якщо призначити генератор об'єкту X зараз?"
  - "Скільки об'єктів покращиться якщо відправити 2 генератори в район Y?"
  - "Як зміниться city score якщо не диспетчити нічого?"

Використовується для:
  - Strategic planning (де відкрити новий Пункт незламності)
  - Before/after comparison для resource allocation
  - Capacity planning на основі прогнозів occupancy
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from app.ml.features import ScoreFeatures
from app.ml.inference import predict_score
from app.ml.routing_ml import predict_assignment_priority

logger = logging.getLogger(__name__)


@dataclass
class InterventionSpec:
    """Опис втручання для what-if аналізу."""

    object_id: str
    intervention_type: str  # "generator", "tech_team", "starlink", "fuel", "evacuation"
    eta_min: int = 30
    effect_battery_pct: float = 100.0  # +100% battery
    effect_power_on: bool = True
    effect_internet_on: bool = True
    effect_occupancy_relief: float = 0.0  # % людей виводимо


@dataclass
class InterventionResult:
    """Результат одного what-if сценарію."""

    object_id: str
    object_name: str
    before_score: float
    after_score: float
    score_delta: float
    before_status: str
    after_status: str
    before_ttc_min: Optional[float]
    after_ttc_min: Optional[float]
    ttc_delta_min: Optional[float]
    will_rescue: bool  # чи покращиться статус


@dataclass
class CounterfactualAnalysis:
    """Сумарний what-if аналіз."""

    baseline_avg_score: float
    baseline_critical_count: int
    post_intervention_avg_score: float
    post_intervention_critical_count: int
    score_improvement: float
    critical_reduction: int
    intervention_results: list[InterventionResult]
    recommendation: str


def _apply_intervention_to_features(
    base_features: ScoreFeatures,
    intervention: InterventionSpec,
) -> ScoreFeatures:
    """Застосовує втручання до features (modifies fields)."""
    data = base_features.model_dump()
    if intervention.intervention_type == "generator":
        # Генератор дає живлення і заряджає батарею
        data["power_on"] = intervention.effect_power_on
        data["has_generator"] = True
        data["generator_on"] = True
        data["battery_pct"] = min(
            100.0, base_features.battery_pct + intervention.effect_battery_pct
        )
        data["battery_est_hours"] = max(24.0, base_features.battery_est_hours)
    elif intervention.intervention_type == "tech_team":
        # Техбригада може полагодити сенсори / покращити умови
        data["co2_ppm"] = max(400.0, base_features.co2_ppm * 0.7)
        data["temp_c"] = max(18.0, min(24.0, base_features.temp_c))
    elif intervention.intervention_type == "starlink":
        data["has_starlink"] = True
        data["internet_on"] = intervention.effect_internet_on
        data["signal"] = 4
    elif intervention.intervention_type == "fuel":
        # Додаткове паливо для генератора
        data["battery_pct"] = min(100.0, base_features.battery_pct + 50.0)
        data["battery_est_hours"] = max(8.0, base_features.battery_est_hours)
    elif intervention.intervention_type == "evacuation":
        # Виводимо частину людей
        new_occ = base_features.occupancy_ratio * (
            1.0 - intervention.effect_occupancy_relief
        )
        data["occupancy_ratio"] = max(0.0, new_occ)
    return ScoreFeatures(**data)


def _estimate_ttc_for_features(features: ScoreFeatures) -> Optional[float]:
    """Грубий прогноз TTC (якщо battery/год відомі)."""
    if features.power_on or features.generator_on:
        return None
    if features.battery_pct <= 20:
        return 0.0
    if features.battery_est_hours <= 0:
        return None
    headroom = features.battery_pct - 20.0
    return (headroom / 100.0) * features.battery_est_hours * 60.0


def analyze_intervention(
    object_name: str,
    base_features: ScoreFeatures,
    intervention: InterventionSpec,
) -> InterventionResult:
    """Аналізує ефект одного втручання."""
    before_pred = predict_score(base_features)
    after_features = _apply_intervention_to_features(base_features, intervention)
    after_pred = predict_score(after_features)

    before_ttc = _estimate_ttc_for_features(base_features)
    after_ttc = _estimate_ttc_for_features(after_features)

    return InterventionResult(
        object_id=intervention.object_id,
        object_name=object_name,
        before_score=before_pred.score,
        after_score=after_pred.score,
        score_delta=round(after_pred.score - before_pred.score, 1),
        before_status=before_pred.status,
        after_status=after_pred.status,
        before_ttc_min=before_ttc,
        after_ttc_min=after_ttc,
        ttc_delta_min=(
            round(after_ttc - before_ttc, 1)
            if before_ttc is not None and after_ttc is not None
            else None
        ),
        will_rescue=after_pred.score >= 70 or after_pred.status == "STABLE",
    )


def run_counterfactual(
    objects_data: list[tuple[str, str, ScoreFeatures]],  # (object_id, name, features)
    interventions: list[InterventionSpec],
) -> CounterfactualAnalysis:
    """
    Запускає counterfactual analysis з кількома interventions.

    Args:
        objects_data: список (object_id, name, base_features)
        interventions: interventions для тестування

    Returns:
        CounterfactualAnalysis з baseline vs post-intervention порівнянням
    """
    if not objects_data:
        return CounterfactualAnalysis(
            baseline_avg_score=0.0,
            baseline_critical_count=0,
            post_intervention_avg_score=0.0,
            post_intervention_critical_count=0,
            score_improvement=0.0,
            critical_reduction=0,
            intervention_results=[],
            recommendation="No data",
        )

    # Baseline (без interventions)
    baseline_scores: list[float] = []
    baseline_critical = 0
    for _oid, _name, features in objects_data:
        pred = predict_score(features)
        baseline_scores.append(pred.score)
        if pred.status == "CRITICAL":
            baseline_critical += 1
    baseline_avg = float(np.mean(baseline_scores))

    # Apply interventions
    intervention_by_obj: dict[str, InterventionSpec] = {
        inv.object_id: inv for inv in interventions
    }
    post_scores: list[float] = []
    post_critical = 0
    intervention_results: list[InterventionResult] = []

    for oid, name, features in objects_data:
        if oid in intervention_by_obj:
            result = analyze_intervention(name, features, intervention_by_obj[oid])
            intervention_results.append(result)
            post_scores.append(result.after_score)
            if result.after_status == "CRITICAL":
                post_critical += 1
        else:
            pred = predict_score(features)
            post_scores.append(pred.score)
            if pred.status == "CRITICAL":
                post_critical += 1

    post_avg = float(np.mean(post_scores))

    # Generate recommendation
    improvement = post_avg - baseline_avg
    critical_reduction = baseline_critical - post_critical
    if improvement > 10 and critical_reduction > 0:
        rec = f"Strongly recommended: avg score +{improvement:.1f}, {critical_reduction} fewer critical objects"
    elif improvement > 0:
        rec = f"Marginal benefit: avg score +{improvement:.1f}"
    elif critical_reduction > 0:
        rec = f"Saves {critical_reduction} critical objects but no avg improvement"
    else:
        rec = "No measurable benefit — consider alternative interventions"

    return CounterfactualAnalysis(
        baseline_avg_score=round(baseline_avg, 1),
        baseline_critical_count=baseline_critical,
        post_intervention_avg_score=round(post_avg, 1),
        post_intervention_critical_count=post_critical,
        score_improvement=round(improvement, 1),
        critical_reduction=critical_reduction,
        intervention_results=intervention_results,
        recommendation=rec,
    )
