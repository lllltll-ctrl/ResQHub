"""
MLflow experiment tracking для ResQHub.

Використовується для:
  - Логування метрик кожного training run (RMSE, MAE, R^2, NDCG, Brier)
  - Логування parameters (n_estimators, max_depth, etc.)
  - Збереження артефактів моделей
  - Порівняння experiments через MLflow UI

Запуск UI:
    mlflow ui --backend-store-uri file:./mlruns

Або programmatic API:
    from app.ml.experiment_tracking import ExperimentTracker
    tracker = ExperimentTracker()
    tracker.start_run("score_v2.0.0")
    ...
    tracker.log_metrics({"rmse": 2.5, "r2": 0.99})
    tracker.end_run()
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)

MLRUNS_DIR = Path(__file__).parent.parent / "mlruns"
MLRUNS_DIR.mkdir(parents=True, exist_ok=True)

# Set MLflow tracking URI to local file store
os.environ.setdefault("MLFLOW_TRACKING_URI", f"file:{MLRUNS_DIR}")


@dataclass
class ExperimentRun:
    """Стан одного experiment run."""

    run_id: str
    experiment_name: str
    run_name: str
    started_at: float
    ended_at: Optional[float] = None
    params: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
    tags: dict[str, str] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)
    status: str = "RUNNING"


class ExperimentTracker:
    """
    Wrapper над MLflow з graceful fallback на local JSONL store.

    Використовується в train.py для логування runs.
    """

    def __init__(
        self,
        experiment_name: str = "resqhub_ml",
        tracking_uri: Optional[str] = None,
    ) -> None:
        self._experiment_name = experiment_name
        self._tracking_uri = tracking_uri or os.environ.get(
            "MLFLOW_TRACKING_URI", f"file:{MLRUNS_DIR}"
        )
        self._active_run: Optional[ExperimentRun] = None
        self._mlflow_available = self._check_mlflow()
        self._fallback_log: list[dict[str, Any]] = []

    def _check_mlflow(self) -> bool:
        try:
            import mlflow

            mlflow.set_tracking_uri(self._tracking_uri)
            return True
        except Exception as e:
            logger.warning("MLflow unavailable, using local fallback: %s", e)
            return False

    def start_run(
        self,
        run_name: str,
        tags: Optional[dict[str, str]] = None,
    ) -> str:
        """Починає новий experiment run."""
        if self._mlflow_available:
            try:
                import mlflow

                mlflow.set_experiment(self._experiment_name)
                run = mlflow.start_run(run_name=run_name)
                if tags:
                    mlflow.set_tags(tags)
                self._active_run = ExperimentRun(
                    run_id=run.info.run_id,
                    experiment_name=self._experiment_name,
                    run_name=run_name,
                    started_at=time.time(),
                    tags=tags or {},
                )
                logger.info(
                    "Started MLflow run: %s (id=%s)",
                    run_name,
                    run.info.run_id,
                )
                return run.info.run_id
            except Exception as e:
                logger.warning("MLflow start_run failed: %s", e)

        # Fallback
        run_id = f"local_{int(time.time() * 1000)}"
        self._active_run = ExperimentRun(
            run_id=run_id,
            experiment_name=self._experiment_name,
            run_name=run_name,
            started_at=time.time(),
            tags=tags or {},
        )
        self._fallback_log.append(
            {"event": "start", "run_id": run_id, "name": run_name}
        )
        return run_id

    def log_params(self, params: dict[str, Any]) -> None:
        """Логує parameters."""
        if self._active_run is None:
            return
        if self._mlflow_available:
            try:
                import mlflow

                mlflow.log_params(
                    {
                        k: v
                        for k, v in params.items()
                        if isinstance(v, (int, float, str))
                    }
                )
            except Exception as e:
                logger.debug("MLflow log_params failed: %s", e)
        self._active_run.params.update(params)
        self._fallback_log.append({"event": "params", "params": params})

    def log_metrics(
        self,
        metrics: dict[str, float],
        step: Optional[int] = None,
    ) -> None:
        """Логує metrics."""
        if self._active_run is None:
            return
        if self._mlflow_available:
            try:
                import mlflow

                mlflow.log_metrics(metrics, step=step)
            except Exception as e:
                logger.debug("MLflow log_metrics failed: %s", e)
        self._active_run.metrics.update(metrics)
        self._fallback_log.append(
            {"event": "metrics", "metrics": metrics, "step": step}
        )

    def log_artifact(self, local_path: str) -> None:
        """Логує artifact (file)."""
        if self._active_run is None:
            return
        if self._mlflow_available:
            try:
                import mlflow

                mlflow.log_artifact(local_path)
            except Exception as e:
                logger.debug("MLflow log_artifact failed: %s", e)
        self._active_run.artifacts.append(local_path)
        self._fallback_log.append({"event": "artifact", "path": local_path})

    def set_tag(self, key: str, value: str) -> None:
        if self._active_run is None:
            return
        if self._mlflow_available:
            try:
                import mlflow

                mlflow.set_tag(key, value)
            except Exception:
                pass
        self._active_run.tags[key] = value

    def end_run(self, status: str = "FINISHED") -> None:
        """Закриває поточний run."""
        if self._active_run is None:
            return
        self._active_run.ended_at = time.time()
        self._active_run.status = status
        if self._mlflow_available:
            try:
                import mlflow

                mlflow.end_run(status=status)
            except Exception as e:
                logger.debug("MLflow end_run failed: %s", e)
        self._fallback_log.append(
            {"event": "end", "run_id": self._active_run.run_id, "status": status}
        )
        # Persist fallback log
        log_path = MLRUNS_DIR / f"{self._active_run.run_id}.jsonl"
        with log_path.open("w") as f:
            for entry in self._fallback_log:
                f.write(json.dumps(entry) + "\n")
        logger.info("Ended run: %s (status=%s)", self._active_run.run_id, status)
        self._active_run = None

    def get_active_run(self) -> Optional[ExperimentRun]:
        return self._active_run


# ─────────────────────────────────────────────────────────────────────
# Convenience: scoring quality tracking
# ─────────────────────────────────────────────────────────────────────
class ScoreQualityTracker:
    """
    Відстежує якість scoring у production (online metric tracking).

    Використовується для моніторингу model degradation.
    """

    def __init__(self, window: int = 100) -> None:
        self._window = window
        self._predictions: list[tuple[float, float, float]] = []
        # (prediction, target, timestamp)

    def record(self, prediction: float, target: float) -> None:
        self._predictions.append((prediction, target, time.time()))
        if len(self._predictions) > self._window:
            self._predictions.pop(0)

    def get_metrics(self) -> dict[str, float]:
        if not self._predictions:
            return {}
        preds = np.array([p[0] for p in self._predictions])
        targets = np.array([p[1] for p in self._predictions])
        errors = preds - targets
        return {
            "n_samples": float(len(self._predictions)),
            "mae": float(np.abs(errors).mean()),
            "rmse": float(np.sqrt((errors**2).mean())),
            "mean_pred": float(preds.mean()),
            "mean_target": float(targets.mean()),
            "bias": float(errors.mean()),
        }
