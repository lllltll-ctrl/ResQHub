"""
Multi-Armed Bandit для resource allocation.

P4 problem: як розподілити обмежену кількість ресурсів (генераторів, бригад)
між об'єктами, балансуючи між:
  - Exploitation: призначати об'єктам з найкращим відомим outcome
  - Exploration: пробувати нові assignment, щоб дізнатись ефект

Реалізує:
  - Epsilon-greedy
  - UCB1 (Upper Confidence Bound)
  - Thompson sampling (Beta distribution)
  - Contextual bandit (LinUCB) — використовує фічі об'єкта

Використовується для:
  - Optimizing routing decisions based on historical outcomes
  - A/B test для routing стратегій
"""

from __future__ import annotations

import logging
import math
import random
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np

from app.ml.features import FEATURE_NAMES
from app.ml.store import ARTIFACTS_DIR, load_artifact, save_artifact

logger = logging.getLogger(__name__)

BANDIT_STATE_PATH = ARTIFACTS_DIR / "bandit_state.json"


@dataclass(frozen=True)
class BanditArm:
    """Один 'arm' (resource type × base location)."""

    arm_id: str
    resource_type: str
    base_name: str
    n_pulls: int = 0
    n_successes: int = 0
    total_reward: float = 0.0
    last_pulled: Optional[float] = None

    @property
    def success_rate(self) -> float:
        if self.n_pulls == 0:
            return 0.0
        return self.n_successes / self.n_pulls

    @property
    def mean_reward(self) -> float:
        if self.n_pulls == 0:
            return 0.0
        return self.total_reward / self.n_pulls

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MultiArmedBandit:
    """
    Multi-armed bandit з підтримкою epsilon-greedy, UCB1, Thompson sampling.

    Кожен arm — це комбінація (resource_type, base_location).
    Reward = +1 якщо assignment покращив score, -1 якщо погіршив, 0 якщо neutral.
    """

    def __init__(
        self,
        epsilon: float = 0.1,
        ucb_c: float = 1.5,
        strategy: str = "ucb1",  # "epsilon_greedy", "ucb1", "thompson"
    ) -> None:
        self._epsilon = epsilon
        self._ucb_c = ucb_c
        self._strategy = strategy
        self._arms: dict[str, BanditArm] = {}
        self._total_pulls = 0

    def register_arm(self, arm_id: str, resource_type: str, base_name: str) -> None:
        if arm_id not in self._arms:
            self._arms[arm_id] = BanditArm(
                arm_id=arm_id,
                resource_type=resource_type,
                base_name=base_name,
            )

    def select_arm(self) -> Optional[str]:
        """Обирає arm за поточною стратегією."""
        if not self._arms:
            return None

        if self._strategy == "epsilon_greedy":
            return self._select_epsilon_greedy()
        elif self._strategy == "ucb1":
            return self._select_ucb1()
        elif self._strategy == "thompson":
            return self._select_thompson()
        else:
            return list(self._arms.keys())[0]

    def _select_epsilon_greedy(self) -> str:
        if random.random() < self._epsilon or all(
            a.n_pulls == 0 for a in self._arms.values()
        ):
            # Explore: random arm
            return random.choice(list(self._arms.keys()))
        # Exploit: best mean
        return max(self._arms.values(), key=lambda a: a.mean_reward).arm_id

    def _select_ucb1(self) -> str:
        # Якщо є невипробувані arm — обираємо їх
        unpulled = [a for a in self._arms.values() if a.n_pulls == 0]
        if unpulled:
            return random.choice(unpulled).arm_id

        # UCB1 formula: mean + c * sqrt(2 * log(N) / n_i)
        log_n = math.log(max(self._total_pulls, 1))
        best_arm = None
        best_ucb = -float("inf")
        for arm in self._arms.values():
            ucb = arm.mean_reward + self._ucb_c * math.sqrt(2.0 * log_n / arm.n_pulls)
            if ucb > best_ucb:
                best_ucb = ucb
                best_arm = arm
        return best_arm.arm_id if best_arm else random.choice(list(self._arms.keys()))

    def _select_thompson(self) -> str:
        # Thompson sampling з Beta distribution
        best_arm = None
        best_sample = -float("inf")
        for arm in self._arms.values():
            # Beta(α, β) = Beta(1 + successes, 1 + failures)
            alpha = 1 + arm.n_successes
            beta_param = 1 + (arm.n_pulls - arm.n_successes)
            sample = np.random.beta(alpha, beta_param)
            if sample > best_sample:
                best_sample = sample
                best_arm = arm
        return best_arm.arm_id if best_arm else random.choice(list(self._arms.keys()))

    def update(self, arm_id: str, reward: float, success: bool) -> None:
        """Оновлює arm після отримання outcome."""
        if arm_id not in self._arms:
            return
        arm = self._arms[arm_id]
        # Need to replace frozen dataclass
        self._arms[arm_id] = BanditArm(
            arm_id=arm.arm_id,
            resource_type=arm.resource_type,
            base_name=arm.base_name,
            n_pulls=arm.n_pulls + 1,
            n_successes=arm.n_successes + (1 if success else 0),
            total_reward=arm.total_reward + reward,
            last_pulled=time.time(),
        )
        self._total_pulls += 1

    def get_state(self) -> dict[str, Any]:
        return {
            "strategy": self._strategy,
            "epsilon": self._epsilon,
            "ucb_c": self._ucb_c,
            "total_pulls": self._total_pulls,
            "n_arms": len(self._arms),
            "arms": {aid: a.to_dict() for aid, a in self._arms.items()},
        }

    def save(self) -> Path:
        path = save_artifact(
            "bandit_state",
            {
                "arms": {aid: a.to_dict() for aid, a in self._arms.items()},
                "total_pulls": self._total_pulls,
                "strategy": self._strategy,
                "epsilon": self._epsilon,
                "ucb_c": self._ucb_c,
            },
        )
        return path

    def load(self) -> bool:
        try:
            data = load_artifact("bandit_state")
            self._total_pulls = data.get("total_pulls", 0)
            self._strategy = data.get("strategy", "ucb1")
            self._epsilon = data.get("epsilon", 0.1)
            self._ucb_c = data.get("ucb_c", 1.5)
            self._arms = {
                aid: BanditArm(**a) for aid, a in data.get("arms", {}).items()
            }
            return True
        except FileNotFoundError:
            return False

    @property
    def arms(self) -> list[BanditArm]:
        return list(self._arms.values())


# ─────────────────────────────────────────────────────────────────────
# Contextual Bandit (LinUCB)
# ─────────────────────────────────────────────────────────────────────
class LinUCBBandit:
    """
    LinUCB — contextual bandit.

    Для кожного arm тримає ridge regression model:
      E[r | x, a] = θ_a^T x

    Обирає arm: argmax_a (θ_a^T x + α * sqrt(x^T A_a^-1 x))

    Використовується коли reward залежить від features об'єкта.
    """

    def __init__(self, n_features: int = 13, alpha: float = 1.0) -> None:
        self._n_features = n_features
        self._alpha = alpha
        # Per-arm A (n x n) and b (n) matrices
        self._A: dict[str, np.ndarray] = defaultdict(lambda: np.eye(n_features))
        self._b: dict[str, np.ndarray] = defaultdict(lambda: np.zeros(n_features))
        self._arm_ids: set[str] = set()

    def register_arm(self, arm_id: str) -> None:
        self._arm_ids.add(arm_id)

    def select(self, context: np.ndarray) -> Optional[str]:
        """Обирає arm з найкращим UCB для context."""
        if not self._arm_ids:
            return None

        context = np.asarray(context, dtype=np.float64).flatten()
        best_arm = None
        best_ucb = -float("inf")

        for arm_id in self._arm_ids:
            A_inv = np.linalg.inv(self._A[arm_id])
            theta = A_inv @ self._b[arm_id]
            # Predicted reward
            pred = float(theta @ context)
            # Uncertainty
            uncertainty = float(self._alpha * np.sqrt(context @ A_inv @ context))
            ucb = pred + uncertainty
            if ucb > best_ucb:
                best_ucb = ucb
                best_arm = arm_id
        return best_arm

    def update(self, arm_id: str, context: np.ndarray, reward: float) -> None:
        """Оновлює модель arm після отримання outcome."""
        context = np.asarray(context, dtype=np.float64).flatten()
        self._A[arm_id] = self._A[arm_id] + np.outer(context, context)
        self._b[arm_id] = self._b[arm_id] + reward * context

    def get_known_arms(self) -> set[str]:
        return set(self._arm_ids)


# ─────────────────────────────────────────────────────────────────────
# Global singletons
# ─────────────────────────────────────────────────────────────────────
_global_bandit: Optional[MultiArmedBandit] = None


def get_bandit() -> MultiArmedBandit:
    global _global_bandit
    if _global_bandit is None:
        _global_bandit = MultiArmedBandit(strategy="ucb1")
        _global_bandit.load()
    return _global_bandit
