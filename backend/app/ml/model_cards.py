"""
Model Cards for ML governance.

Кожна модель має model card — стандартизований документ з:
  - Intended use
  - Training data
  - Performance metrics
  - Limitations
  - Ethical considerations
  - Maintenance info

Це best practice з Google's Model Card framework.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class ModelCard:
    """Model card для однієї ML-моделі."""

    model_name: str
    model_version: str
    model_type: str  # "regression", "classification", "ranker", "anomaly_detection"
    intended_use: str
    training_data: str
    features: list[str]
    target: str
    metrics: dict[str, float]
    limitations: list[str]
    ethical_considerations: list[str]
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    owner: str = "ResQHub ML Team"
    contact: str = "ml@resqhub.local"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────
# Pre-defined model cards
# ─────────────────────────────────────────────────────────────────────
SCORE_MODEL_CARD = ModelCard(
    model_name="Resilience Score Predictor",
    model_version="1.0.0",
    model_type="regression",
    intended_use=(
        "Прогнозує Resilience Score (0-100) для критичних об'єктів міста "
        "(укриття, лікарні, школи) на основі телеметрії. Використовується "
        "для real-time моніторингу та пріоритизації ресурсів під час блекаутів."
    ),
    training_data=(
        "Синтетичний датасет 8000 прикладів з 4 сценаріями: NORMAL, "
        "PARTIAL_DISTRESS, FULL_BLACKOUT, CRITICAL_OVERLOAD. Модель навчена "
        "на фізично-обґрунтованій цільовій функції, що включає виживаність "
        "систем, комфорт мешканців та пріоритет для міських служб."
    ),
    features=[
        "battery_pct (0-100)",
        "battery_est_hours (0-72)",
        "temp_c (-30 to 60)",
        "co2_ppm (300-5000)",
        "occupancy_ratio (0-2)",
        "criticality (1-5)",
        "has_generator (bool)",
        "has_starlink (bool)",
        "power_on (bool)",
        "internet_on (bool)",
        "signal (0-4)",
        "humidity_pct (0-100)",
        "generator_on (bool)",
    ],
    target="Resilience Score (0-100)",
    metrics={
        "rmse": 2.49,
        "mae": 1.79,
        "r2": 0.993,
        "status_accuracy": 0.935,
        "brier_critical": 0.050,
        "brier_warning": 0.065,
        "brier_stable": 0.015,
    },
    limitations=[
        "Навчена на синтетичних даних, не на реальних блекаутах",
        "Не враховує сезонні патерни (зима vs літо)",
        "Припускає, що battery_est_hours — точне значення (на практиці залежить від навантаження)",
        "Не включає зовнішні фактори (погода, свята, нічний час)",
    ],
    ethical_considerations=[
        "Може вплинути на рішення про розподіл ресурсів — потребує human-in-the-loop",
        "Synthetic data може мати biases проти реальних сценаріїв",
        "Диспетчер має бачити SHAP explanations перед прийняттям рішень",
        "Не має використовуватись для автоматичних рішень без human review",
    ],
)


RANKER_MODEL_CARD = ModelCard(
    model_name="Assignment Priority Ranker",
    model_version="1.0.0",
    model_type="ranker",
    intended_use=(
        "Ранжує об'єкти за пріоритетом для призначення обмежених ресурсів "
        "(генераторів, бригад, палива). Замінює hand-tuned зважену формулу."
    ),
    training_data=(
        "Синтетичний датасет з 4000 прикладів у групах по 20 об'єктів. "
        "Target — релевантність 0/1/2 на основі TTC та criticality."
    ),
    features=[
        "current_score (0-100)",
        "time_to_critical_min (хвилини)",
        "criticality (1-5)",
        "occupancy_ratio (0-2)",
        "battery_pct (0-100)",
        "has_generator (bool)",
        "has_starlink (bool)",
        "power_on (bool)",
        "ttc_missing (bool)",
        "status_severity (0-2)",
    ],
    target="Relevance 0/1/2 (low/medium/high urgency)",
    metrics={
        "ndcg_at_5": 1.000,
        "ndcg_at_10": 0.999,
    },
    limitations=[
        "Не враховує відстань від баз техніки (це робить VRP solver окремо)",
        "Парні дані синтетичні, ranking може не відповідати реальним операційним пріоритетам",
    ],
    ethical_considerations=[
        "Пріоритизація впливає на те, хто отримає допомогу першим — потребує публічного обговорення",
        "Модель не включає соціальні фактори (інвалідність, діти, медичні потреби)",
    ],
)


ANOMALY_MODEL_CARD = ModelCard(
    model_name="Telemetry Anomaly Detector",
    model_version="1.0.0",
    model_type="anomaly_detection",
    intended_use=(
        "Виявляє аномальні telemetry readings (зламані сенсори, неможливі "
        "комбінації, outliers). Використовується для попередження про "
        "несправності обладнання."
    ),
    training_data="2000 нормальних прикладів з training dataset",
    features=[
        "Всі 13 фіч з score model",
    ],
    target="Binary: is_anomaly (True/False)",
    metrics={
        "contamination": 0.05,
        "n_estimators": 200,
    },
    limitations=[
        "Навчений на синтетичних 'нормальних' даних — може не знати про всі реальні anomaly patterns",
        "Не розрізняє типи аномалій (для цього є Root Cause Analyzer)",
        "При anomaly spike може бути 'cry wolf' ефект",
    ],
    ethical_considerations=[
        "False positives можуть призвести до зайвих перевірок обладнання",
        "False negatives можуть призвести до прийняття невалідних readings у ML score",
    ],
)


DRIFT_DETECTOR_CARD = ModelCard(
    model_name="Feature Drift Detector",
    model_version="1.0.0",
    model_type="drift_detection",
    intended_use=(
        "Виявляє розбіжності між training distribution і live telemetry. "
        "Використовується для early warning про model degradation."
    ),
    training_data="2000 reference samples з training dataset",
    features=[
        "Всі 13 фіч з score model",
    ],
    target="Drift score (KS statistic + p-value)",
    metrics={
        "test": "Kolmogorov-Smirnov 2-sample",
        "threshold_p": 0.05,
        "window_size": 200,
    },
    limitations=[
        "Не виявляє concept drift (зміну зв'язку між фіч і target)",
        "Чутливий до розміру current window — при <30 observations може не спрацювати",
    ],
    ethical_considerations=[
        "Drift detection має спрацьовувати швидко, щоб уникнути прийняття поганих рішень",
    ],
)


# ─────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────
MODEL_CARDS: dict[str, ModelCard] = {
    "score_model": SCORE_MODEL_CARD,
    "ranker_model": RANKER_MODEL_CARD,
    "anomaly_detector": ANOMALY_MODEL_CARD,
    "drift_detector": DRIFT_DETECTOR_CARD,
}


def get_model_card(model_name: str) -> Optional[ModelCard]:
    return MODEL_CARDS.get(model_name)


def list_model_cards() -> list[str]:
    return list(MODEL_CARDS.keys())


def export_all_cards(output_dir: Path) -> None:
    """Експортує всі model cards у JSON для governance audit."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, card in MODEL_CARDS.items():
        path = output_dir / f"{name}_card.json"
        path.write_text(json.dumps(card.to_dict(), indent=2, ensure_ascii=False))
