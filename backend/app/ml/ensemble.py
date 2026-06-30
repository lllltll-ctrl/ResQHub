"""
Multi-model ensemble: RandomForest + XGBoost + LightGBM.

P3 improvement: aggregating predictions of 3 різних моделей часто
дає кращу якість і robustість ніж будь-яка окрема.

Ансамбль стратегії:
  - Mean averaging (simple)
  - Weighted averaging (на основі validation performance)
  - Stacking (meta-learner)

Поточна реалізація: mean averaging (найпростіший і ефективний).

Зберігається як окремий артефакт `ensemble_model_X.Y.Z.joblib`.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np

from app.ml.features import FEATURE_NAMES, ScoreFeatures
from app.ml.inference import _load_score, predict_score
from app.ml.store import (
    ARTIFACTS_DIR,
    SCORE_MODEL_VERSION,
    load_artifact,
    save_artifact,
)

logger = logging.getLogger(__name__)

ENSEMBLE_VERSION = "1.0.0"
ENSEMBLE_MODEL_NAME = f"ensemble_model_{ENSEMBLE_VERSION}"


@dataclass
class EnsembleMember:
    """Один член ансамблю."""

    name: str
    model: Any
    weight: float
    val_score: float  # validation R^2


@dataclass
class EnsembleConfig:
    """Конфігурація ансамблю."""

    members: list[EnsembleMember]
    version: str


def _train_xgboost(
    X: np.ndarray, y: np.ndarray, random_state: int = 42
) -> tuple[Any, dict[str, float]]:
    """Тренує XGBoost regressor."""
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import r2_score, mean_absolute_error
    import xgboost as xgb

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=random_state
    )
    model = xgb.XGBRegressor(
        n_estimators=200,
        max_depth=8,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.7,
        random_state=random_state,
        n_jobs=-1,
        tree_method="hist",
    )
    model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)
    y_pred = model.predict(X_test)
    return model, {
        "r2": float(r2_score(y_test, y_pred)),
        "mae": float(mean_absolute_error(y_test, y_pred)),
    }


def _train_lightgbm(
    X: np.ndarray, y: np.ndarray, random_state: int = 42
) -> tuple[Any, dict[str, float]]:
    """Тренує LightGBM regressor."""
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import r2_score, mean_absolute_error
    import lightgbm as lgb

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=random_state
    )
    model = lgb.LGBMRegressor(
        n_estimators=300,
        max_depth=8,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.7,
        random_state=random_state,
        n_jobs=-1,
        verbose=-1,
    )
    model.fit(X_train, y_train, eval_set=[(X_test, y_test)])
    y_pred = model.predict(X_test)
    return model, {
        "r2": float(r2_score(y_test, y_pred)),
        "mae": float(mean_absolute_error(y_test, y_pred)),
    }


def _train_random_forest(
    X: np.ndarray, y: np.ndarray, random_state: int = 42
) -> tuple[Any, dict[str, float]]:
    """Тренує RandomForestRegressor."""
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import r2_score, mean_absolute_error

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=random_state
    )
    model = RandomForestRegressor(
        n_estimators=200,
        max_depth=12,
        min_samples_split=4,
        n_jobs=-1,
        random_state=random_state,
    )
    model.fit(X_train, y_train)
    y_pred = model.predict(X_test)
    return model, {
        "r2": float(r2_score(y_test, y_pred)),
        "mae": float(mean_absolute_error(y_test, y_pred)),
    }


def train_ensemble(n_samples: int = 8000, seed: int = 42) -> dict[str, Any]:
    """
    Тренує ансамбль з 3 моделей і зберігає на диск.
    """
    from app.ml.dataset import generate_dataset

    print("=" * 60)
    print("Training Multi-Model Ensemble")
    print("=" * 60)

    bundle = generate_dataset(n_samples=n_samples, seed=seed)
    X, y = bundle.X, bundle.y

    members_data: list[tuple[str, Any, dict]] = []

    print("\n[1/3] Training RandomForest...")
    rf, rf_metrics = _train_random_forest(X, y, random_state=seed)
    print(f"      R^2={rf_metrics['r2']:.4f}, MAE={rf_metrics['mae']:.3f}")
    members_data.append(("random_forest", rf, rf_metrics))

    print("\n[2/3] Training XGBoost...")
    xgb_model, xgb_metrics = _train_xgboost(X, y, random_state=seed)
    print(f"      R^2={xgb_metrics['r2']:.4f}, MAE={xgb_metrics['mae']:.3f}")
    members_data.append(("xgboost", xgb_model, xgb_metrics))

    print("\n[3/3] Training LightGBM...")
    lgb_model, lgb_metrics = _train_lightgbm(X, y, random_state=seed)
    print(f"      R^2={lgb_metrics['r2']:.4f}, MAE={lgb_metrics['mae']:.3f}")
    members_data.append(("lightgbm", lgb_model, lgb_metrics))

    # Compute weights based on R^2
    r2_values = np.array([m["r2"] for _, _, m in members_data])
    # Softmax-like weighting: w_i = exp(r2_i) / sum(exp(r2_j))
    exp_r2 = np.exp(r2_values * 10)  # Scale для різниці
    weights = exp_r2 / exp_r2.sum()

    members: list[EnsembleMember] = []
    for (name, model, m), w in zip(members_data, weights):
        members.append(
            EnsembleMember(
                name=name,
                model=model,
                weight=float(w),
                val_score=m["r2"],
            )
        )
        print(f"  {name:15s} R^2={m['r2']:.4f} weight={w:.3f}")

    # Save ensemble
    payload = {
        "members": [
            {
                "name": m.name,
                "model": m.model,
                "weight": m.weight,
                "val_score": m.val_score,
            }
            for m in members
        ],
        "feature_names": list(FEATURE_NAMES),
        "version": ENSEMBLE_VERSION,
    }
    save_artifact(ENSEMBLE_MODEL_NAME, payload)
    print(f"\n  ✓ Saved ensemble: {ENSEMBLE_MODEL_NAME}.joblib")

    # Save metrics
    metrics_path = ARTIFACTS_DIR / f"ensemble_model_{ENSEMBLE_VERSION}.meta.json"
    metrics_path.write_text(
        json.dumps(
            {
                "version": ENSEMBLE_VERSION,
                "trained_at": time.time(),
                "n_samples": n_samples,
                "members": [
                    {"name": m.name, "weight": m.weight, "val_score": m.val_score}
                    for m in members
                ],
            },
            indent=2,
        )
    )

    return {
        "members": [
            {"name": m.name, "r2": m.val_score, "weight": m.weight} for m in members
        ],
        "version": ENSEMBLE_VERSION,
    }


def predict_ensemble(features: ScoreFeatures) -> dict[str, Any]:
    """Прогноз через ансамбль (weighted average)."""
    try:
        artifact = load_artifact(ENSEMBLE_MODEL_NAME)
    except FileNotFoundError:
        # Fallback на single model
        pred = predict_score(features)
        return {
            "score": pred.score,
            "method": "single_model_fallback",
            "member_scores": {},
        }

    X = features.to_array()
    weighted_sum = 0.0
    total_weight = 0.0
    member_scores: dict[str, float] = {}

    for m in artifact["members"]:
        try:
            score = float(m["model"].predict(X)[0])
            weighted_sum += score * m["weight"]
            total_weight += m["weight"]
            member_scores[m["name"]] = round(score, 2)
        except Exception as e:
            logger.warning("Ensemble member %s failed: %s", m["name"], e)

    if total_weight > 0:
        final_score = weighted_sum / total_weight
    else:
        final_score = predict_score(features).score

    final_score = float(np.clip(final_score, 0.0, 100.0))

    # Status
    if final_score >= 70:
        status = "STABLE"
    elif final_score >= 40:
        status = "WARNING"
    else:
        status = "CRITICAL"

    return {
        "score": round(final_score, 1),
        "status": status,
        "method": "ensemble",
        "version": ENSEMBLE_VERSION,
        "member_scores": member_scores,
    }
