"""
Pytest fixtures for ResQHub tests.
"""

import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# Додаємо backend корінь до PYTHONPATH
BACKEND_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_ROOT))


@pytest.fixture(autouse=True, scope="session")
def protect_ml_artifacts():
    """Захищає бойові ML-артефакти від тестів.

    Деякі тести викликають fit()/save_artifact(), які пишуть у
    app/ml/artifacts. Без цього fixture кожен запуск pytest перезаписував
    натреновану score-модель і anomaly detector випадковими даними.
    Робимо бекап перед сесією і відновлюємо все після неї.
    """
    from app.ml.store import ARTIFACTS_DIR

    artifacts = Path(ARTIFACTS_DIR)
    backup_root = Path(tempfile.mkdtemp(prefix="resqhub_artifacts_"))
    backup = backup_root / "artifacts"
    if artifacts.exists():
        shutil.copytree(artifacts, backup)
    try:
        yield
    finally:
        if backup.exists():
            # Відновлюємо оригінальний стан: тестові файли прибираємо,
            # оригінальні повертаємо як були.
            if artifacts.exists():
                shutil.rmtree(artifacts, ignore_errors=True)
            shutil.copytree(backup, artifacts)
        shutil.rmtree(backup_root, ignore_errors=True)
