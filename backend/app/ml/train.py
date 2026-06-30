"""
Training pipeline for ResQHub ML models.

Запуск:
    python -m app.ml.train

Що тренує:
  1. SCORE-модель (RandomForestRegressor) — прогнозує Resilience Score 0-100
     + threshold-based status classifier {STABLE, WARNING, CRITICAL}.
  2. RANKER-модель (LightGBM ranker) — для призначення генераторів,
     замінює ручну зважену формулу з routing_engine.compute_priority_score.

Метрики:
  - RMSE, MAE, R^2 (regression)
  - Brier score, accuracy, classification report (status)
  - NDCG@5 (ranker)
  - Calibration plot (PNG)

Усі артефакти зберігаються у app/ml/artifacts/ з версіонуванням.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

import joblib
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import (
    brier_score_loss,
    mean_absolute_error,
    mean_squared_error,
    r2_score,
)
from sklearn.model_selection import train_test_split

from app.ml.dataset import (
    N_SAMPLES,
    generate_dataset,
    int_to_status,
    status_to_int,
)
from app.ml.features import FEATURE_NAMES, ScoreFeatures
from app.ml.store import (
    RANKER_METADATA_PATH,
    RANKER_MODEL_PATH,
    RANKER_MODEL_VERSION,
    SCORE_METADATA_PATH,
    SCORE_MODEL_PATH,
    SCORE_MODEL_VERSION,
    save_artifact,
)


# ─────────────────────────────────────────────────────────────────────
# Status classification wrapper
# ─────────────────────────────────────────────────────────────────────
@dataclass
class StatusThresholds:
    stable: float = 70.0
    warning: float = 40.0

    def predict(self, score: float) -> str:
        if score >= self.stable:
            return "STABLE"
        if score >= self.warning:
            return "WARNING"
        return "CRITICAL"


# ─────────────────────────────────────────────────────────────────────
# Score regressor + threshold pair
# ─────────────────────────────────────────────────────────────────────
def train_score_model(
    X: np.ndarray, y: np.ndarray, random_state: int = 42
) -> tuple[RandomForestRegressor, dict[str, Any]]:
    """
    Тренує RandomForestRegressor для Resilience Score.
    Повертає (model, metrics).
    """
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=random_state
    )

    model = RandomForestRegressor(
        n_estimators=200,
        max_depth=12,
        min_samples_split=4,
        min_samples_leaf=2,
        max_features=0.7,
        n_jobs=-1,
        random_state=random_state,
    )
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    y_pred_clipped = np.clip(y_pred, 0.0, 100.0)

    rmse = float(np.sqrt(mean_squared_error(y_test, y_pred_clipped)))
    mae = float(mean_absolute_error(y_test, y_pred_clipped))
    r2 = float(r2_score(y_test, y_pred_clipped))

    return model, {
        "rmse": rmse,
        "mae": mae,
        "r2": r2,
        "n_train": int(X_train.shape[0]),
        "n_test": int(X_test.shape[0]),
    }


def evaluate_status_calibration(
    y_true_score: np.ndarray,
    y_pred_score: np.ndarray,
    y_true_status: np.ndarray,
) -> dict[str, Any]:
    """
    Оцінює якість порогового status-класифікатора на основі predicted score.
    """
    thresholds = StatusThresholds()
    y_pred_status = np.array([thresholds.predict(s) for s in y_pred_score])
    y_true_int = np.array([status_to_int(s) for s in y_true_status])
    y_pred_int = np.array([status_to_int(s) for s in y_pred_status])

    accuracy = float(np.mean(y_pred_int == y_true_int))

    # Brier scores (one-vs-rest)
    briers = {}
    for cls, name in [(0, "critical"), (1, "warning"), (2, "stable")]:
        y_true_bin = (y_true_int == cls).astype(int)
        y_pred_bin = (y_pred_int == cls).astype(int)
        briers[name] = float(brier_score_loss(y_true_bin, y_pred_bin))

    return {
        "status_accuracy": accuracy,
        "brier_critical": briers["critical"],
        "brier_warning": briers["warning"],
        "brier_stable": briers["stable"],
    }


# ─────────────────────────────────────────────────────────────────────
# Ranker (LightGBM)
# ─────────────────────────────────────────────────────────────────────
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


def _build_ranker_dataset(
    n_samples: int = 4000, seed: int = 42
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Будує синтетичний датасет для ranker-моделі.

    Структура: N "ситуацій" (груп), кожна з K об'єктів-кандидатів.
    Target — релевантність 0/1/2, де:
        2 = потребує генератора негайно (TTC < 30 хв)
        1 = потребує генератора протягом години
        0 = не потребує

    LightGBM ranker навчається ранжувати об'єкти ВСЕРЕДИНІ групи.
    """
    bundle = generate_dataset(n_samples=n_samples, seed=seed)
    rng = np.random.default_rng(seed)

    X = bundle.X
    battery_pct = X[:, 0]
    battery_hours = X[:, 1]
    power_on = X[:, 8].astype(bool)
    has_generator = X[:, 6].astype(bool)
    criticality = X[:, 5]
    occ_ratio = X[:, 4]
    has_starlink = X[:, 7].astype(bool)

    # Груба оцінка TTC
    ttc_min = np.where(
        power_on | has_generator,
        999.0,  # no urgency
        np.clip(battery_pct - 20.0, 0, 100) / 100.0 * battery_hours * 60.0,
    )
    ttc_missing = (~power_on & ~has_generator).astype(np.float64)

    current_score = bundle.y

    status_severity = np.zeros(n_samples, dtype=np.float64)
    status_severity[ttc_min < 60] = 1.0
    status_severity[ttc_min < 30] = 2.0

    ranker_X = np.column_stack(
        [
            current_score,
            ttc_min,
            criticality,
            occ_ratio,
            battery_pct,
            has_generator.astype(np.float64),
            has_starlink.astype(np.float64),
            power_on.astype(np.float64),
            ttc_missing,
            status_severity,
        ]
    ).astype(np.float64)

    # Relevance labels
    y_relevance = np.zeros(n_samples, dtype=np.int32)
    y_relevance[ttc_min < 60] = 1
    y_relevance[ttc_min < 30] = 2
    y_relevance = np.where(criticality >= 4, np.maximum(y_relevance, 1), y_relevance)
    y_relevance = np.where((criticality >= 5) & (ttc_min < 90), 2, y_relevance)

    # Групи: пакуємо по 20 прикладів у групу
    GROUP_SIZE = 20
    n_groups = n_samples // GROUP_SIZE
    used = n_groups * GROUP_SIZE
    ranker_X = ranker_X[:used]
    y_relevance = y_relevance[:used]
    groups = np.full(n_groups, GROUP_SIZE, dtype=np.int64)

    return ranker_X, y_relevance, groups


def train_ranker_model(random_state: int = 42) -> tuple[Any, dict[str, Any]]:
    """
    Тренує LightGBM ranker для assignment priority.
    """
    import lightgbm as lgb

    X, y, groups = _build_ranker_dataset()
    n_groups = len(groups)
    n_test_groups = max(1, int(n_groups * 0.2))
    rng = np.random.default_rng(random_state)
    test_idx = set(rng.choice(n_groups, size=n_test_groups, replace=False).tolist())

    # Split by group
    train_rows: list[int] = []
    test_rows: list[int] = []
    cursor = 0
    for g_idx, g_size in enumerate(groups):
        if g_idx in test_idx:
            test_rows.extend(range(cursor, cursor + int(g_size)))
        else:
            train_rows.extend(range(cursor, cursor + int(g_size)))
        cursor += int(g_size)

    X_train = X[train_rows]
    X_test = X[test_rows]
    y_train = y[train_rows]
    y_test = y[test_rows]
    # Групи у train/test (group -> count)
    train_group_set = set(range(n_groups)) - test_idx
    g_train = np.array(
        [int(groups[i]) for i in sorted(train_group_set)], dtype=np.int64
    )
    g_test = np.array([int(groups[i]) for i in sorted(test_idx)], dtype=np.int64)

    train_data = lgb.Dataset(
        X_train, label=y_train, group=g_train, feature_name=list(RANKER_FEATURE_NAMES)
    )
    test_data = lgb.Dataset(
        X_test, label=y_test, group=g_test, feature_name=list(RANKER_FEATURE_NAMES)
    )

    params = {
        "objective": "lambdarank",
        "metric": "ndcg",
        "ndcg_eval_at": [5, 10],
        "learning_rate": 0.05,
        "num_leaves": 31,
        "min_data_in_leaf": 20,
        "feature_fraction": 0.9,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "verbose": -1,
        "random_state": random_state,
    }

    model = lgb.train(
        params,
        train_data,
        num_boost_round=300,
        valid_sets=[test_data],
        callbacks=[lgb.early_stopping(stopping_rounds=30, verbose=False)],
    )

    # NDCG eval
    y_pred = model.predict(X_test)
    ndcg_at_5 = _approximate_ndcg(y_test, y_pred, g_test, k=5)
    ndcg_at_10 = _approximate_ndcg(y_test, y_pred, g_test, k=10)

    return model, {
        "ndcg_at_5": float(ndcg_at_5),
        "ndcg_at_10": float(ndcg_at_10),
        "best_iteration": int(model.best_iteration),
    }


def _approximate_ndcg(
    y_true: np.ndarray, y_pred: np.ndarray, groups: np.ndarray, k: int
) -> float:
    """Обчислює NDCG@k для ранжування по групах (multi-element)."""
    from sklearn.metrics import ndcg_score

    ndcgs = []
    start = 0
    for g_size in groups:
        g_size = int(g_size)
        if g_size < 2:
            start += g_size
            continue
        yt = y_true[start : start + g_size].reshape(1, -1)
        yp = y_pred[start : start + g_size].reshape(1, -1)
        try:
            ndcgs.append(float(ndcg_score(yt, yp, k=min(k, g_size))))
        except Exception:
            pass
        start += g_size
    return float(np.mean(ndcgs)) if ndcgs else 0.0


# ─────────────────────────────────────────────────────────────────────
# SHAP explainer
# ─────────────────────────────────────────────────────────────────────
def compute_shap_values(
    model: RandomForestRegressor, X_background: np.ndarray
) -> dict[str, float]:
    """
    Обчислює mean(|SHAP value|) для кожної фічі — global feature importance.
    Повертає dict {feature_name: importance}.
    """
    try:
        import shap
    except ImportError:
        return {}

    explainer = shap.TreeExplainer(model)
    # Використовуємо лише 200 прикладів для швидкості
    sample = X_background[:200]
    shap_values = explainer.shap_values(sample)
    mean_abs = np.abs(shap_values).mean(axis=0)
    return {name: float(mean_abs[i]) for i, name in enumerate(FEATURE_NAMES)}


# ─────────────────────────────────────────────────────────────────────
# Calibration plot
# ─────────────────────────────────────────────────────────────────────
def write_calibration_plot(
    y_true: np.ndarray, y_pred: np.ndarray, out_path: Path
) -> None:
    """Зберігає calibration plot (reliability diagram) у PNG."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return

    bins = np.linspace(0, 100, 11)
    bin_centers = (bins[:-1] + bins[1:]) / 2
    bin_true_means = []
    bin_pred_means = []
    bin_counts = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        mask = (y_pred >= lo) & (y_pred < hi)
        if mask.sum() == 0:
            bin_true_means.append(np.nan)
            bin_pred_means.append(np.nan)
            bin_counts.append(0)
        else:
            bin_true_means.append(float(y_true[mask].mean()))
            bin_pred_means.append(float(y_pred[mask].mean()))
            bin_counts.append(int(mask.sum()))

    fig, ax = plt.subplots(figsize=(6, 6))
    valid = ~np.isnan(bin_true_means)
    ax.plot([0, 100], [0, 100], "k--", label="Ідеальна калібрація")
    ax.scatter(
        np.array(bin_pred_means)[valid],
        np.array(bin_true_means)[valid],
        s=np.array(bin_counts)[valid] * 2,
        c="tab:orange",
        alpha=0.7,
    )
    ax.set_xlabel("Predicted score")
    ax.set_ylabel("Actual score (bin mean)")
    ax.set_title("Score Calibration Plot")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=100)
    plt.close(fig)


# ─────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────
def main() -> None:
    print("=" * 60)
    print("ResQHub ML Training Pipeline")
    print("=" * 60)

    # 1. Генеруємо датасет
    print(f"\n[1/5] Генерую тренувальний датасет ({N_SAMPLES} samples)...")
    bundle = generate_dataset(n_samples=N_SAMPLES)
    X, y, y_status = bundle.X, bundle.y, bundle.y_status
    print(f"      X.shape={X.shape}, y.shape={y.shape}")
    print(
        f"      Status distribution: "
        f"STABLE={int((y_status == 'STABLE').sum())}, "
        f"WARNING={int((y_status == 'WARNING').sum())}, "
        f"CRITICAL={int((y_status == 'CRITICAL').sum())}"
    )

    # 2. Тренуємо score-модель
    print("\n[2/5] Треную RandomForestRegressor для score-моделі...")
    regressor, score_metrics = train_score_model(X, y)
    print(
        f"      RMSE={score_metrics['rmse']:.2f}, "
        f"MAE={score_metrics['mae']:.2f}, "
        f"R^2={score_metrics['r2']:.3f}"
    )

    # 3. Оцінюємо status-класифікацію
    print("\n[3/5] Оцінюю status-класифікацію...")
    X_train, X_test, y_train, y_test, s_train, s_test = train_test_split(
        X, y, y_status, test_size=0.2, random_state=42
    )
    y_pred_score = regressor.predict(X_test)
    status_metrics = evaluate_status_calibration(y_test, y_pred_score, s_test)
    print(f"      Status accuracy={status_metrics['status_accuracy']:.3f}")
    print(
        f"      Brier scores: critical={status_metrics['brier_critical']:.3f}, "
        f"warning={status_metrics['brier_warning']:.3f}, "
        f"stable={status_metrics['brier_stable']:.3f}"
    )

    # 4. SHAP feature importance
    print("\n[4/5] Обчислюю SHAP feature importance...")
    importance = compute_shap_values(regressor, X_train)
    if importance:
        top5 = sorted(importance.items(), key=lambda kv: -kv[1])[:5]
        print("      Top-5 features:")
        for name, val in top5:
            print(f"        {name:25s} = {val:.4f}")

    # 5. Тренуємо ranker-модель
    print("\n[5/5] Треную LightGBM ranker для assignment priority...")
    ranker, ranker_metrics = train_ranker_model()
    print(
        f"      NDCG@5={ranker_metrics['ndcg_at_5']:.3f}, "
        f"NDCG@10={ranker_metrics['ndcg_at_10']:.3f}"
    )

    # ───── Збереження артефактів ─────
    print("\n" + "=" * 60)
    print("Зберігаю артефакти...")
    print("=" * 60)

    thresholds = StatusThresholds()
    score_payload = {
        "regressor": regressor,
        "status_thresholds": {
            "stable": thresholds.stable,
            "warning": thresholds.warning,
        },
        "feature_names": list(FEATURE_NAMES),
        "version": SCORE_MODEL_VERSION,
    }
    save_artifact(f"score_model_{SCORE_MODEL_VERSION}", score_payload)
    print(f"  ✓ {SCORE_MODEL_PATH.name}")

    score_metadata = {
        "version": SCORE_MODEL_VERSION,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "n_samples": int(N_SAMPLES),
        "feature_names": list(FEATURE_NAMES),
        "metrics": {**score_metrics, **status_metrics},
        "shap_importance": importance,
    }
    SCORE_METADATA_PATH.write_text(json.dumps(score_metadata, indent=2))
    print(f"  ✓ {SCORE_METADATA_PATH.name}")

    ranker_payload = {
        "model": ranker,
        "feature_names": list(RANKER_FEATURE_NAMES),
        "version": RANKER_MODEL_VERSION,
    }
    save_artifact(f"ranker_model_{RANKER_MODEL_VERSION}", ranker_payload)
    print(f"  ✓ {RANKER_MODEL_PATH.name}")

    ranker_metadata = {
        "version": RANKER_MODEL_VERSION,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "feature_names": list(RANKER_FEATURE_NAMES),
        "metrics": ranker_metrics,
    }
    RANKER_METADATA_PATH.write_text(json.dumps(ranker_metadata, indent=2))
    print(f"  ✓ {RANKER_METADATA_PATH.name}")

    # Calibration plot
    plot_path = Path(__file__).parent / "artifacts" / "calibration_plot.png"
    write_calibration_plot(y_test, np.clip(y_pred_score, 0, 100), plot_path)
    print(f"  ✓ {plot_path.name}")

    print("\n✓ Тренування завершено успішно.")
    print(f"  Score model: v{SCORE_MODEL_VERSION}")
    print(f"  Ranker model: v{RANKER_MODEL_VERSION}")


if __name__ == "__main__":
    main()
