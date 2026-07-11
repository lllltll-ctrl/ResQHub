"""
AI-копілот диспетчера.

Відповідає на питання природною мовою, спираючись на ЖИВИЙ стан міста
(об'єкти, бали, TTC, рекомендації) — це «grounding», модель не вигадує.
Використовує Gemini REST API (безкоштовний tier). Ключ — з env GEMINI_API_KEY.

Навмисно без важкого SDK: один POST через stdlib urllib, щоб не тягнути
залежності й не ламати Docker-білд.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services import orchestrator

logger = logging.getLogger(__name__)

_STATUS_UA = {
    "STABLE": "стабільний",
    "WARNING": "увага",
    "CRITICAL": "критичний",
    "RESCUE_IN_TRANSIT": "допомога в дорозі",
}

SYSTEM_PROMPT = (
    "Ти — AI-помічник диспетчера ResQHub у місті Житомир під час блекаутів. "
    "Твоя задача — допомагати рятувати критичні об'єкти (укриття, лікарні, "
    "школи, пункти незламності, пожежні частини).\n"
    "ПРАВИЛА:\n"
    "- Відповідай СТИСЛО, українською, по суті (2-6 речень або короткий список).\n"
    "- Спирайся ВИКЛЮЧНО на надані дані про об'єкти. Не вигадуй об'єктів чи цифр.\n"
    "- Якщо просять план — дай конкретні кроки: кому і що везти ПЕРШИМ "
    "(генератор/батарея/паливо/Starlink/техбригада) і чому.\n"
    "- Пріоритет: об'єкти без живлення, з малим запасом часу (TTC), високою "
    "критичністю та заповненістю.\n"
    "- Якщо даних для відповіді бракує — чесно скажи про це."
)


def build_city_context(db: Session) -> dict:
    """Компактний зріз живого стану міста для передачі в LLM."""
    summary = orchestrator.get_dashboard_summary(db)
    rows = orchestrator.get_objects_with_state(db)
    scenario = orchestrator.get_active_scenario(db)

    objects = []
    for row in rows:
        obj = row["object"]
        t = row["telemetry"]
        s = row["score"]
        objects.append(
            {
                "назва": obj.name,
                "тип": obj.type.value,
                "район": obj.district,
                "статус": _STATUS_UA.get(
                    s.status.value if s else "STABLE", "стабільний"
                ),
                "бал": round(s.score) if s else None,
                "заряд_%": round(t.battery_pct) if t else None,
                "живлення_мережа": bool(t.power_on) if t else None,
                "генератор_працює": bool(t.generator_on) if t else None,
                "має_генератор": bool(obj.has_generator),
                "хв_до_критичного": (
                    round(s.time_to_critical_min)
                    if s and s.time_to_critical_min is not None
                    else None
                ),
                "людей": (f"{t.occupancy}/{obj.capacity}" if t else None),
                "критичність": obj.criticality,
            }
        )

    try:
        recs = orchestrator.get_routing_recommendations(db, limit=5)
        recommendations = [
            {"назва": r.object_name, "пріоритет": round(r.priority_score), "чому": r.justification}
            for r in recs
        ]
    except Exception:
        recommendations = []

    return {
        "місто": "Житомир",
        "середній_бал": summary.get("avg_city_score"),
        "стабільних": summary.get("stable"),
        "увага": summary.get("warning"),
        "критичних": summary.get("critical"),
        "активний_сценарій": scenario.type.value if scenario else "нормальний режим",
        "рекомендації_ML": recommendations,
        "об_єкти": objects,
    }


def _call_gemini(question: str, context: dict) -> str:
    api_key = settings.gemini_api_key
    if not api_key:
        raise RuntimeError("no_api_key")

    model = settings.gemini_model or "gemini-2.0-flash"
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    user_text = (
        f"Питання диспетчера: {question}\n\n"
        f"ЖИВИЙ стан міста (JSON):\n"
        f"{json.dumps(context, ensure_ascii=False)}"
    )
    body = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 800},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


def answer(db: Session, question: str) -> dict:
    """Повертає {answer, configured}. Ніколи не кидає — щоб UI не падав."""
    question = (question or "").strip()
    if not question:
        return {"answer": "Постав питання про стан міста.", "configured": True}
    if not settings.gemini_api_key:
        return {
            "answer": (
                "Копілот не налаштований: адміну треба додати GEMINI_API_KEY у .env "
                "бекенду. Безкоштовний ключ — на ai.google.dev."
            ),
            "configured": False,
        }
    try:
        context = build_city_context(db)
        return {"answer": _call_gemini(question, context), "configured": True}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:300]
        logger.warning("Gemini HTTP %s: %s", e.code, detail)
        return {
            "answer": f"LLM повернув помилку {e.code}. Перевір ключ/модель.",
            "configured": True,
        }
    except Exception as e:
        logger.exception("Copilot failed: %s", e)
        return {"answer": "Не вдалося отримати відповідь. Спробуй ще раз.", "configured": True}
