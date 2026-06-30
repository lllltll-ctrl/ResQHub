"""
SHAP-based explainability для score-моделі.

Використовується у фронтенді для відображення "чому саме такий score".
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from app.ml.features import FEATURE_NAMES, ScoreFeatures
from app.ml.inference import _load_score


_explainer_cache: dict[str, object] = {}


def _get_explainer():
    """Кешований SHAP TreeExplainer для поточної score-моделі."""
    key = "tree_explainer"
    if key not in _explainer_cache:
        try:
            import shap

            artifact = _load_score()
            _explainer_cache[key] = shap.TreeExplainer(artifact["regressor"])
        except Exception:
            _explainer_cache[key] = None
    return _explainer_cache.get(key)


def explain_score(features: ScoreFeatures) -> dict[str, float]:
    """
    Повертає SHAP values для одного прикладу у форматі {feature_name: contribution}.
    Позитивне значення = фіча підвищує score, негативне = знижує.
    """
    explainer = _get_explainer()
    if explainer is None:
        return {name: 0.0 for name in FEATURE_NAMES}

    X = features.to_array()
    try:
        shap_values = explainer.shap_values(X)
        if isinstance(shap_values, list):
            shap_values = shap_values[0]
        values = np.asarray(shap_values[0], dtype=np.float64)
    except Exception:
        return {name: 0.0 for name in FEATURE_NAMES}

    contributions: dict[str, float] = {}
    for i, name in enumerate(FEATURE_NAMES):
        if i < len(values):
            contributions[name] = round(float(values[i]), 3)
        else:
            contributions[name] = 0.0
    return contributions


def top_contributors(features: ScoreFeatures, n: int = 3) -> list[tuple[str, float]]:
    """
    Повертає top-N фіч за |SHAP value| — для UI-пояснення.
    """
    contribs = explain_score(features)
    items = sorted(contribs.items(), key=lambda kv: -abs(kv[1]))
    return items[:n]
