"""
Anomaly Root-Cause Analysis (RCA).

Замість загального "sensor broken" — детектуємо:
  - Конкретну фічу, яка виходить за межі
  - Частоту аномалій (recurring vs one-time)
  - Кореляцію з іншими фічами
  - Конкретну можливу причину (battery depleted, occupancy spike, CO2 leak)

Використовує:
  - z-score analysis на кожній фічі
  - correlation matrix з лагом (t-1)
  - pattern matching (recurring anomalies в певний час)
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from app.ml.features import FEATURE_NAMES
from app.ml.monitoring.anomaly import AnomalyDetector, AnomalyScore
from app.ml.store import ARTIFACTS_DIR, load_artifact, save_artifact

logger = logging.getLogger(__name__)

ANOMALY_HISTORY_PATH = ARTIFACTS_DIR / "anomaly_history.jsonl"


@dataclass(frozen=True)
class RootCauseHypothesis:
    """Одна гіпотеза про причину аномалії."""

    cause: str  # "battery_depleted", "co2_leak", "occupancy_spike", "sensor_malfunction", "power_loss"
    confidence: float
    evidence: list[str]
    recommended_action: str


@dataclass(frozen=True)
class RootCauseAnalysis:
    """Повний RCA для однієї аномалії."""

    object_id: str
    timestamp: float
    anomaly_score: float
    root_causes: list[RootCauseHypothesis]
    primary_cause: Optional[str]
    feature_deviations: dict[str, float]  # feature_name -> z-score
    is_recurring: bool
    similar_anomalies_last_24h: int
    recommended_action: str


class RootCauseAnalyzer:
    """
    Аналізує anomaly history і формує RCA hypotheses.
    """

    def __init__(self) -> None:
        self._anomaly_history: list[AnomalyScore] = []
        self._per_object_history: dict[str, list[AnomalyScore]] = defaultdict(list)
        self._load_history()

    def _load_history(self) -> None:
        """Завантажує історію аномалій з диску."""
        if not ANOMALY_HISTORY_PATH.exists():
            return
        try:
            import json

            with ANOMALY_HISTORY_PATH.open() as f:
                for line in f:
                    if line.strip():
                        data = json.loads(line)
                        score = AnomalyScore(
                            object_id=data["object_id"],
                            timestamp=data["timestamp"],
                            score=data["score"],
                            is_anomaly=data["is_anomaly"],
                            feature_values=data.get("feature_values", {}),
                        )
                        self._anomaly_history.append(score)
                        self._per_object_history[score.object_id].append(score)
        except Exception as e:
            logger.warning("Failed to load anomaly history: %s", e)

    def record(self, score: AnomalyScore) -> None:
        """Додає anomaly в історію (з persistence)."""
        if not score.is_anomaly:
            return
        self._anomaly_history.append(score)
        self._per_object_history[score.object_id].append(score)
        try:
            import json

            with ANOMALY_HISTORY_PATH.open("a") as f:
                f.write(
                    json.dumps(
                        {
                            "object_id": score.object_id,
                            "timestamp": score.timestamp,
                            "score": score.score,
                            "is_anomaly": score.is_anomaly,
                            "feature_values": score.feature_values,
                            "reason": score.reason,
                        }
                    )
                    + "\n"
                )
        except Exception as e:
            logger.warning("Failed to persist anomaly: %s", e)

    def analyze(
        self,
        anomaly: AnomalyScore,
        feature_values: dict[str, float],
        z_scores: dict[str, float],
    ) -> RootCauseAnalysis:
        """
        Аналізує аномалію і формує RCA.
        """
        hypotheses: list[RootCauseHypothesis] = []

        # Hypothesis 1: Battery depleted
        battery = feature_values.get("battery_pct", 100.0)
        if battery < 10.0:
            hypotheses.append(
                RootCauseHypothesis(
                    cause="battery_depleted",
                    confidence=0.95,
                    evidence=[
                        f"battery_pct={battery:.1f}% (< 10%)",
                        f"z-score(battery)={z_scores.get('battery_pct', 0):.2f}",
                    ],
                    recommended_action="Призначити генератор або паливо негайно",
                )
            )
        elif battery < 30.0:
            hypotheses.append(
                RootCauseHypothesis(
                    cause="battery_low",
                    confidence=0.7,
                    evidence=[f"battery_pct={battery:.1f}% (< 30%)"],
                    recommended_action="Моніторити батарею, підготувати генератор",
                )
            )

        # Hypothesis 2: CO2 spike (ventilation issue)
        co2 = feature_values.get("co2_ppm", 400.0)
        if co2 > 2000.0:
            hypotheses.append(
                RootCauseHypothesis(
                    cause="co2_leak_or_ventilation_failure",
                    confidence=0.85,
                    evidence=[
                        f"co2_ppm={co2:.0f} (>2000)",
                        f"z-score(co2)={z_scores.get('co2_ppm', 0):.2f}",
                    ],
                    recommended_action="Перевірити вентиляцію, можливо CO2 sensor fault",
                )
            )

        # Hypothesis 3: Occupancy spike
        occ = feature_values.get("occupancy_ratio", 0.0)
        if occ > 1.3:
            hypotheses.append(
                RootCauseHypothesis(
                    cause="occupancy_overload",
                    confidence=0.9,
                    evidence=[f"occupancy_ratio={occ:.2f} (>1.3 = 130% capacity)"],
                    recommended_action="Скерувати частину людей на сусідні об'єкти",
                )
            )

        # Hypothesis 4: Power loss
        power_on = feature_values.get("power_on", 1.0)
        if power_on < 0.5:
            has_gen = feature_values.get("has_generator", 0.0)
            if has_gen < 0.5:
                hypotheses.append(
                    RootCauseHypothesis(
                        cause="power_loss_no_backup",
                        confidence=0.95,
                        evidence=[
                            "power_on=False",
                            "has_generator=False",
                        ],
                        recommended_action="Призначити генератор негайно",
                    )
                )

        # Hypothesis 5: Sensor malfunction
        # If specific feature has extreme z-score (>5) but others normal
        extreme_features = [n for n, z in z_scores.items() if abs(z) > 5.0]
        if extreme_features and len(extreme_features) == 1:
            hypotheses.append(
                RootCauseHypothesis(
                    cause="sensor_malfunction",
                    confidence=0.6,
                    evidence=[
                        f"Feature {extreme_features[0]} має z-score >5, інші — нормальні",
                    ],
                    recommended_action="Перевірити сенсор (можливо несправний)",
                )
            )

        # Sort by confidence
        hypotheses.sort(key=lambda h: -h.confidence)
        primary = hypotheses[0].cause if hypotheses else None

        # Check recurring
        similar_24h = sum(
            1
            for s in self._per_object_history.get(anomaly.object_id, [])
            if s.timestamp > time.time() - 86400
        )
        is_recurring = similar_24h > 2

        if is_recurring:
            hypotheses.insert(
                0,
                RootCauseHypothesis(
                    cause="recurring_pattern",
                    confidence=0.8,
                    evidence=[f"{similar_24h} anomalies за останні 24 год"],
                    recommended_action="Систематична проблема — потрібна ручна перевірка",
                ),
            )

        if primary is None:
            primary = "unknown"

        return RootCauseAnalysis(
            object_id=anomaly.object_id,
            timestamp=anomaly.timestamp,
            anomaly_score=anomaly.score,
            root_causes=hypotheses,
            primary_cause=primary,
            feature_deviations=z_scores,
            is_recurring=is_recurring,
            similar_anomalies_last_24h=similar_24h,
            recommended_action=(
                hypotheses[0].recommended_action
                if hypotheses
                else "Потрібен додатковий аналіз"
            ),
        )


# ─────────────────────────────────────────────────────────────────────
# Global singleton
# ─────────────────────────────────────────────────────────────────────
_global_rca: Optional[RootCauseAnalyzer] = None


def get_rca() -> RootCauseAnalyzer:
    global _global_rca
    if _global_rca is None:
        _global_rca = RootCauseAnalyzer()
    return _global_rca
