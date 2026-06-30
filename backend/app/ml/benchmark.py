"""
Performance benchmarking для ML models.

Вимірює:
  - Latency: p50, p95, p99 (мілісекунди)
  - Throughput: predictions per second
  - Memory: peak RSS під час inference
  - CPU: load average

Використовується для:
  - SLA monitoring
  - Capacity planning
  - Regression detection (якщо нова версія повільніша)
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np

from app.ml.store import ARTIFACTS_DIR

logger = logging.getLogger(__name__)

BENCHMARK_HISTORY_PATH = ARTIFACTS_DIR / "benchmark_history.jsonl"


@dataclass
class BenchmarkResult:
    """Результат одного benchmark."""

    model_name: str
    model_version: str
    n_samples: int
    total_time_sec: float
    mean_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    throughput_per_sec: float
    peak_memory_mb: Optional[float] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PerformanceBenchmark:
    """
    Benchmark утиліта для ML models.

    Використання:
        bench = PerformanceBenchmark("score_model", "1.0.0")
        result = bench.run(n_samples=1000)
        print(result)
    """

    def __init__(self, model_name: str, model_version: str) -> None:
        self._model_name = model_name
        self._model_version = model_version

    def run(
        self,
        predict_fn,
        n_samples: int = 1000,
        feature_dim: int = 13,
    ) -> BenchmarkResult:
        """
        Запускає benchmark на n_samples.

        Args:
            predict_fn: callable(features_array) -> predictions
            n_samples: кількість predictions
            feature_dim: розмір feature vector
        """
        # Generate random features
        rng = np.random.RandomState(42)
        X = rng.normal(0, 1, (n_samples, feature_dim))

        # Warmup
        for _ in range(10):
            _ = predict_fn(X[:1])

        # Measure
        latencies: list[float] = []
        start_total = time.time()

        for i in range(n_samples):
            x = X[i : i + 1]
            t0 = time.perf_counter()
            _ = predict_fn(x)
            t1 = time.perf_counter()
            latencies.append((t1 - t0) * 1000.0)  # ms

        total_time = time.time() - start_total

        # Memory (Linux only mostly)
        peak_memory_mb: Optional[float] = None
        try:
            import resource

            usage = resource.getrusage(resource.RUSAGE_SELF)
            peak_memory_mb = usage.ru_maxrss / 1024.0  # KB to MB
        except Exception:
            pass

        latencies_arr = np.array(latencies)
        result = BenchmarkResult(
            model_name=self._model_name,
            model_version=self._model_version,
            n_samples=n_samples,
            total_time_sec=total_time,
            mean_latency_ms=float(latencies_arr.mean()),
            p50_latency_ms=float(np.percentile(latencies_arr, 50)),
            p95_latency_ms=float(np.percentile(latencies_arr, 95)),
            p99_latency_ms=float(np.percentile(latencies_arr, 99)),
            throughput_per_sec=n_samples / total_time,
            peak_memory_mb=peak_memory_mb,
        )

        # Persist
        try:
            with BENCHMARK_HISTORY_PATH.open("a") as f:
                f.write(json.dumps(result.to_dict()) + "\n")
        except Exception as e:
            logger.warning("Failed to persist benchmark: %s", e)

        logger.info(
            "Benchmark %s v%s: p50=%.2fms, p95=%.2fms, p99=%.2fms, throughput=%.1f/s",
            self._model_name,
            self._model_version,
            result.p50_latency_ms,
            result.p95_latency_ms,
            result.p99_latency_ms,
            result.throughput_per_sec,
        )
        return result


def get_benchmark_history(limit: int = 50) -> list[dict[str, Any]]:
    """Повертає останні benchmarks."""
    if not BENCHMARK_HISTORY_PATH.exists():
        return []
    out = []
    try:
        with BENCHMARK_HISTORY_PATH.open() as f:
            for line in f:
                if line.strip():
                    out.append(json.loads(line))
    except Exception as e:
        logger.warning("Failed to read benchmark history: %s", e)
    return out[-limit:]


def run_default_benchmarks() -> list[BenchmarkResult]:
    """Запускає benchmarks на основних моделях."""
    from app.ml.inference import predict_score, _load_score
    from app.ml.features import ScoreFeatures
    from app.ml.routing_ml import predict_assignment_priority
    from app.ml.inference import model_versions

    results: list[BenchmarkResult] = []
    versions = model_versions()

    # Score model
    try:
        artifact = _load_score()
        regressor = artifact["regressor"]

        def _score_predict(X: np.ndarray) -> np.ndarray:
            return regressor.predict(X)

        bench = PerformanceBenchmark("score_model", versions["score_model"])
        result = bench.run(_score_predict, n_samples=500, feature_dim=13)
        results.append(result)
    except Exception as e:
        logger.warning("Score model benchmark failed: %s", e)

    return results
