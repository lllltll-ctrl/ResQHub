"""
Concept drift detection для online learning.

На відміну від feature drift (Kolmogorov-Smirnov test на вхідних фічах),
concept drift виявляє зміну ЗВ'ЯЗКУ між фіч і target.

Реалізує ADWIN-подібний алгоритм:
  - Sliding window predictions
  - Якщо MAE нових predictions значно вище baseline → drift
  - Adaptive window size (росте/звужується залежно від drift)

Використовується в online_learning.py для trigger reset.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ConceptDriftEvent:
    """Подія concept drift."""

    timestamp: float
    detector: str  # "adwin", "page_hinkley", "ddm"
    metric_before: float
    metric_after: float
    confidence: float
    recommended_action: str  # "reset", "retrain", "monitor"


class ADWINDetector:
    """
    ADWIN (Adaptive Windowing) — sliding window concept drift detector.

    Зберігає два підвікна: "reference" (старий) і "current" (новий).
    Якщо mean(reference) і mean(current) суттєво різні — drift.

    Спрощена версія (без повного exponential histogram).
    """

    def __init__(
        self,
        delta: float = 0.002,  # confidence parameter
        max_window: int = 1000,
        min_window: int = 30,
    ) -> None:
        self._delta = delta
        self._max_window = max_window
        self._min_window = min_window
        self._window: deque[float] = deque(maxlen=max_window)
        self._drift_history: list[ConceptDriftEvent] = []

    def add(self, error: float) -> Optional[ConceptDriftEvent]:
        """Додає нову помилку prediction. Повертає event якщо drift виявлено."""
        self._window.append(error)

        if len(self._window) < self._min_window * 2:
            return None

        # Sliding cut: спробуємо різні точки поділу
        n = len(self._window)
        window_array = np.array(list(self._window))

        # Знаходимо оптимальну точку поділу
        best_cut = self._min_window
        max_diff = 0.0
        for cut in range(self._min_window, n - self._min_window):
            ref_mean = window_array[:cut].mean()
            cur_mean = window_array[cut:].mean()
            diff = abs(cur_mean - ref_mean)
            if diff > max_diff:
                max_diff = diff
                best_cut = cut

        # Hoeffding bound test
        m = n
        m1 = best_cut
        m2 = n - best_cut
        epsilon = np.sqrt((1.0 / (2.0 * m)) * np.log(2.0 / self._delta))

        ref_mean = window_array[:m1].mean()
        cur_mean = window_array[m1:].mean()

        if abs(cur_mean - ref_mean) >= epsilon:
            # Drift detected
            confidence = min(1.0, max_diff / max(epsilon * 2, 1e-6))
            event = ConceptDriftEvent(
                timestamp=time.time(),
                detector="adwin",
                metric_before=float(ref_mean),
                metric_after=float(cur_mean),
                confidence=confidence,
                recommended_action="reset" if confidence > 0.7 else "retrain",
            )
            self._drift_history.append(event)
            # Trim window to current side
            for _ in range(m1):
                if self._window:
                    self._window.popleft()
            logger.warning(
                "ADWIN drift: ref_mean=%.3f, cur_mean=%.3f, confidence=%.2f",
                ref_mean,
                cur_mean,
                confidence,
            )
            return event
        return None

    @property
    def n_observations(self) -> int:
        return len(self._window)

    @property
    def current_mean(self) -> float:
        return float(np.mean(list(self._window))) if self._window else 0.0

    @property
    def drift_count(self) -> int:
        return len(self._drift_history)

    def get_history(self) -> list[ConceptDriftEvent]:
        return list(self._drift_history)


class PageHinkleyDetector:
    """
    Page-Hinkley test — sequential analysis для concept drift.

    Виявляє зміну mean у послідовності (assumes Gaussian noise).
    """

    def __init__(
        self,
        threshold: float = 50.0,
        alpha: float = 0.005,
    ) -> None:
        self._threshold = threshold
        self._alpha = alpha
        self._sum = 0.0
        self._n = 0
        self._mean = 0.0
        self._cum_dev = 0.0
        self._min_cum_dev = float("inf")
        self._drift_history: list[ConceptDriftEvent] = []

    def add(self, error: float) -> Optional[ConceptDriftEvent]:
        self._n += 1
        # Update running mean incrementally
        old_mean = self._mean
        self._sum += error
        self._mean = self._sum / self._n
        # Cumulative deviation from overall mean
        self._cum_dev += error - self._mean
        # m_T statistic
        m_T = self._cum_dev
        # min_{t<T} m_t (використовуємо min до поточного)
        ph_stat = m_T - self._min_cum_dev
        # Update min AFTER computing
        if m_T < self._min_cum_dev:
            self._min_cum_dev = m_T

        if ph_stat > self._threshold:
            event = ConceptDriftEvent(
                timestamp=time.time(),
                detector="page_hinkley",
                metric_before=old_mean,
                metric_after=error,
                confidence=min(1.0, ph_stat / self._threshold),
                recommended_action="retrain",
            )
            self._drift_history.append(event)
            # Reset
            self._sum = 0.0
            self._n = 0
            self._mean = 0.0
            self._cum_dev = 0.0
            self._min_cum_dev = float("inf")
            logger.warning("Page-Hinkley drift: ph_stat=%.2f", ph_stat)
            return event
        return None

    @property
    def n_observations(self) -> int:
        return self._n

    @property
    def current_mean(self) -> float:
        return self._mean

    @property
    def drift_count(self) -> int:
        return len(self._drift_history)


class DDMDetector:
    """
    Drift Detection Method (DDM) — базується на помилках та їх std.

    Використовується для binary classification, але можна адаптувати
    для regression (error distribution).
    """

    def __init__(
        self,
        warning_level: float = 2.0,  # std deviations
        drift_level: float = 3.0,
        min_samples: int = 30,
    ) -> None:
        self._warning = warning_level
        self._drift = drift_level
        self._min_samples = min_samples
        self._errors: list[float] = []
        self._drift_history: list[ConceptDriftEvent] = []
        self._baseline_mean: Optional[float] = None
        self._baseline_std: Optional[float] = None

    def add(self, error: float) -> Optional[ConceptDriftEvent]:
        self._errors.append(error)
        if len(self._errors) < self._min_samples:
            return None

        # Compute statistics on first half (baseline)
        if self._baseline_mean is None and len(self._errors) >= self._min_samples * 2:
            mid = len(self._errors) // 2
            self._baseline_mean = float(np.mean(self._errors[:mid]))
            self._baseline_std = float(np.std(self._errors[:mid]))

        if self._baseline_std is None or self._baseline_std < 1e-9:
            return None

        # Test latest errors
        window = self._errors[-self._min_samples :]
        cur_mean = float(np.mean(window))
        z_score = (cur_mean - self._baseline_mean) / self._baseline_std

        if z_score > self._drift:
            event = ConceptDriftEvent(
                timestamp=time.time(),
                detector="ddm",
                metric_before=self._baseline_mean,
                metric_after=cur_mean,
                confidence=min(1.0, z_score / self._drift),
                recommended_action="reset",
            )
            self._drift_history.append(event)
            # Reset baseline
            self._baseline_mean = cur_mean
            self._baseline_std = float(np.std(window))
            self._errors = list(window)
            logger.warning("DDM drift: z=%.2f", z_score)
            return event
        return None

    @property
    def n_observations(self) -> int:
        return len(self._errors)

    @property
    def drift_count(self) -> int:
        return len(self._drift_history)


# ─────────────────────────────────────────────────────────────────────
# Composite detector (3-way vote)
# ─────────────────────────────────────────────────────────────────────
class ConceptDriftMonitor:
    """
    Моніторить concept drift через 3 різних detector.
    Якщо хоча б 2 з 3 спрацьовують — drift confirmed.
    """

    def __init__(self) -> None:
        self.adwin = ADWINDetector()
        self.page_hinkley = PageHinkleyDetector()
        self.ddm = DDMDetector()
        self._events: list[ConceptDriftEvent] = []

    def add(self, error: float) -> Optional[ConceptDriftEvent]:
        """Додає помилку, повертає event якщо drift confirmed (2+ detectors)."""
        events: list[ConceptDriftEvent] = []
        for det in [self.adwin, self.page_hinkley, self.ddm]:
            ev = det.add(error)
            if ev is not None:
                events.append(ev)

        if len(events) >= 2:
            # Aggregate confidence
            confidence = float(np.mean([e.confidence for e in events]))
            combined = ConceptDriftEvent(
                timestamp=time.time(),
                detector="composite",
                metric_before=float(np.mean([e.metric_before for e in events])),
                metric_after=float(np.mean([e.metric_after for e in events])),
                confidence=confidence,
                recommended_action="reset" if confidence > 0.7 else "retrain",
            )
            self._events.append(combined)
            logger.warning(
                "Concept drift confirmed: %d/%d detectors, confidence=%.2f",
                len(events),
                3,
                confidence,
            )
            return combined
        return None

    @property
    def n_observations(self) -> int:
        return self.adwin.n_observations

    @property
    def n_drifts(self) -> int:
        return len(self._events)

    def health(self) -> dict[str, object]:
        return {
            "n_observations": self.n_observations,
            "n_drifts": self.n_drifts,
            "adwin_drifts": self.adwin.drift_count,
            "page_hinkley_drifts": self.page_hinkley.drift_count,
            "ddm_drifts": self.ddm.drift_count,
            "adwin_mean": self.adwin.current_mean,
            "page_hinkley_mean": self.page_hinkley.current_mean,
        }


_global_monitor: Optional[ConceptDriftMonitor] = None


def get_concept_drift_monitor() -> ConceptDriftMonitor:
    global _global_monitor
    if _global_monitor is None:
        _global_monitor = ConceptDriftMonitor()
    return _global_monitor
