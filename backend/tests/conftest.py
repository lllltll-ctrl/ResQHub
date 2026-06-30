"""
Pytest fixtures for ResQHub tests.
"""

import sys
from pathlib import Path

# Додаємо backend корінь до PYTHONPATH
BACKEND_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_ROOT))
