"""
Model artifact registry for ResQHub ML.

Версіонування:
  - SCORE_MODEL_VERSION    — оновлюється при кожному перетренуванні
  - RANKER_MODEL_VERSION   — те саме для LightGBM ranker

Усі артефакти зберігаються у app/ml/artifacts/.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import joblib

ARTIFACTS_DIR = Path(__file__).parent / "artifacts"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

SCORE_MODEL_VERSION = "1.0.0"
RANKER_MODEL_VERSION = "1.0.0"

SCORE_MODEL_PATH = ARTIFACTS_DIR / f"score_model_{SCORE_MODEL_VERSION}.joblib"
RANKER_MODEL_PATH = ARTIFACTS_DIR / f"ranker_model_{RANKER_MODEL_VERSION}.joblib"
SCORE_METADATA_PATH = ARTIFACTS_DIR / f"score_model_{SCORE_MODEL_VERSION}.meta.json"
RANKER_METADATA_PATH = ARTIFACTS_DIR / f"ranker_model_{RANKER_MODEL_VERSION}.meta.json"


@dataclass(frozen=True)
class ScoreArtifact:
    """Контейнер для score-моделі + метаданих."""

    regressor: object
    status_classifier: object
    feature_names: tuple[str, ...]
    version: str


@dataclass(frozen=True)
class RankerArtifact:
    """Контейнер для ranker-моделі + метаданих."""

    model: object
    feature_names: tuple[str, ...]
    version: str


def save_artifact(artifact_name: str, payload: dict) -> Path:
    """Серіалізує артефакт через joblib."""
    path = ARTIFACTS_DIR / f"{artifact_name}.joblib"
    joblib.dump(payload, path, compress=3)
    return path


def load_artifact(artifact_name: str) -> dict:
    """Завантажує артефакт з диску."""
    path = ARTIFACTS_DIR / f"{artifact_name}.joblib"
    if not path.exists():
        raise FileNotFoundError(
            f"ML artifact '{artifact_name}' not found at {path}. "
            f"Запустіть: python -m app.ml.train"
        )
    return joblib.load(path)


def artifact_exists(artifact_name: str) -> bool:
    return (ARTIFACTS_DIR / f"{artifact_name}.joblib").exists()
