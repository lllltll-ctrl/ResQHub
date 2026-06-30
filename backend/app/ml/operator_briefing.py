"""
LLM-based operator briefing (P2).

Генерує людино-читабельний narrative для диспетчера/журі на основі:
  - ML score та status
  - SHAP contributions (топ-3 фактори)
  - Anomaly detection
  - Drift detection
  - TTC forecast

Два режими:
  - "template" — детерміністичний (без LLM, для fast demo)
  - "llm" — використовує LLM (через OpenAI API або локальну модель)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

from app.ml.explain import explain_score
from app.ml.features import ScoreFeatures

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OperatorBriefing:
    """Згенерований брифінг для оператора."""

    summary: str
    severity: str
    recommended_actions: list[str]
    key_factors: list[tuple[str, float]]
    model_confidence: float
    method: str  # "template" or "llm"


def generate_template_briefing(
    object_name: str,
    object_type: str,
    features: ScoreFeatures,
    ml_score: float,
    ml_status: str,
    ml_confidence: float,
    anomaly_detected: bool,
    drift_detected: bool,
    ttc_minutes: Optional[float] = None,
) -> OperatorBriefing:
    """Детерміністичний брифінг з SHAP values + actions."""
    contribs = explain_score(features)
    # Top-3 за абсолютним значенням
    top_factors = sorted(contribs.items(), key=lambda kv: -abs(kv[1]))[:3]

    # Severity
    if ml_status == "CRITICAL":
        severity = "CRITICAL"
    elif ml_status == "WARNING":
        severity = "WARNING"
    else:
        severity = "STABLE"

    # Summary
    battery = features.battery_pct
    co2 = features.co2_ppm
    occ_ratio = features.occupancy_ratio

    if ml_status == "CRITICAL":
        summary = (
            f"{object_name} ({object_type}) знаходиться в КРИТИЧНОМУ стані. "
            f"Resilience Score = {ml_score:.1f}/100. "
            f"Батарея: {battery:.0f}%, CO₂: {co2:.0f}ppm, "
            f"заповненість: {occ_ratio * 100:.0f}%."
        )
    elif ml_status == "WARNING":
        summary = (
            f"{object_name} ({object_type}) потребує уваги. "
            f"Resilience Score = {ml_score:.1f}/100. "
            f"Батарея: {battery:.0f}%, CO₂: {co2:.0f}ppm."
        )
    else:
        summary = (
            f"{object_name} ({object_type}) працює стабільно. "
            f"Resilience Score = {ml_score:.1f}/100."
        )

    # Recommended actions
    actions: list[str] = []
    if ttc_minutes is not None and ttc_minutes < 60:
        actions.append(
            f"Призначити генератор/бригаду НЕГАЙНО (TTC={ttc_minutes:.0f} хв)"
        )
    if battery < 30 and not features.has_generator:
        actions.append("Забезпечити резервне живлення")
    if co2 > 1500:
        actions.append("Покращити вентиляцію (високий CO₂)")
    if occ_ratio > 1.0:
        actions.append("Розвантажити об'єкт або скерувати частину людей на сусідні")
    if not features.internet_on and features.has_starlink:
        actions.append("Активувати Starlink для зв'язку")
    if anomaly_detected:
        actions.append("⚠️ Перевірити сенсори (виявлено аномалію в reading)")
    if drift_detected:
        actions.append("📊 Model drift detected — рекомендовано перетренування")
    if ml_confidence < 0.7:
        actions.append(
            f"⚠️ ML-модель невпевнена (confidence={ml_confidence:.2f}) — "
            "перевірити вручну"
        )
    if not actions:
        actions.append("Продовжувати моніторинг у штатному режимі")

    return OperatorBriefing(
        summary=summary,
        severity=severity,
        recommended_actions=actions,
        key_factors=top_factors,
        model_confidence=ml_confidence,
        method="template",
    )


def generate_llm_briefing(
    object_name: str,
    object_type: str,
    features: ScoreFeatures,
    ml_score: float,
    ml_status: str,
    ml_confidence: float,
    anomaly_detected: bool,
    drift_detected: bool,
    ttc_minutes: Optional[float] = None,
) -> OperatorBriefing:
    """
    LLM-based briefing — використовує OpenAI API якщо OPENAI_API_KEY заданий,
    інакше fallback на template.

    Це optional — у прод-оточенні без API ключа повертає template.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.debug("No OPENAI_API_KEY, falling back to template briefing")
        return generate_template_briefing(
            object_name=object_name,
            object_type=object_type,
            features=features,
            ml_score=ml_score,
            ml_status=ml_status,
            ml_confidence=ml_confidence,
            anomaly_detected=anomaly_detected,
            drift_detected=drift_detected,
            ttc_minutes=ttc_minutes,
        )

    try:
        import openai

        client = openai.OpenAI(api_key=api_key)
        contribs = explain_score(features)
        top_factors = sorted(contribs.items(), key=lambda kv: -abs(kv[1]))[:3]

        prompt = f"""Ти — диспетчер міської системи моніторингу енергостійкості.

Об'єкт: {object_name} (тип: {object_type})
ML Score: {ml_score:.1f}/100
ML Status: {ml_status}
ML Confidence: {ml_confidence:.2f}
Батарея: {features.battery_pct:.0f}%
CO₂: {features.co2_ppm:.0f}ppm
Заповненість: {features.occupancy_ratio * 100:.0f}%
Температура: {features.temp_c:.0f}°C
TTC: {f"{ttc_minutes:.0f} хв" if ttc_minutes is not None else "стабільно"}
Топ-фактори ML: {top_factors}
Anomaly: {anomaly_detected}, Drift: {drift_detected}

Сформулюй:
1. Коротке резюме (1-2 речення)
2. Список рекомендованих дій (3-5 пунктів)
3. Severity: STABLE/WARNING/CRITICAL

Відповідай українською, лаконічно, професійно."""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
            temperature=0.3,
        )
        text = response.choices[0].message.content or ""

        # Парсинг LLM output (naive — для demo)
        severity = "STABLE"
        for s in ["CRITICAL", "WARNING", "STABLE"]:
            if s in text.upper():
                severity = s
                break

        return OperatorBriefing(
            summary=text.split("\n")[0] if text else "(LLM повернув порожнє)",
            severity=severity,
            recommended_actions=[
                line.strip("-• 0123456789.").strip()
                for line in text.split("\n")
                if line.strip().startswith(("-", "•", "1", "2", "3", "4", "5"))
            ],
            key_factors=top_factors,
            model_confidence=ml_confidence,
            method="llm",
        )
    except Exception as e:
        logger.exception("LLM briefing failed: %s", e)
        return generate_template_briefing(
            object_name=object_name,
            object_type=object_type,
            features=features,
            ml_score=ml_score,
            ml_status=ml_status,
            ml_confidence=ml_confidence,
            anomaly_detected=anomaly_detected,
            drift_detected=drift_detected,
            ttc_minutes=ttc_minutes,
        )
