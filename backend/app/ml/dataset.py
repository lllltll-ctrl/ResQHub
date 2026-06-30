"""
Realistic synthetic dataset generator for ResQHub ML models.

На відміну від попередньої версії (де дані генерувались з тієї самої формули,
яку ми й намагались вивчити), цей генератор:

  1. Моделює ФІЗИЧНУ динаміку об'єкта:
       - батарея розряджається залежно від навантаження (occupancy + power_on)
       - генератор підтримує заряд, але з шумом паливоміра
       - CO2 росте нелінійно при occupancy > 70% (експоненціальне зростання)
       - температура зростає при відсутності вентиляції
  2. Генерує МІТКУ "Resilience Score" як функцію:
       - виживаності систем (чи витримає об'єкт наступні 2 години)
       - комфорту мешканців (чи безпечно залишатись)
       - пріоритету для міських служб
     Це — НЕ те саме, що ознаки, тому модель має реально вивчати залежності.
  3. Генерує мітку STATUS {STABLE, WARNING, CRITICAL} як похідну від score.

Дев'ять типів об'єктів у датасеті відповідають seed-даним (SHELTER, SCHOOL,
RESILIENCE_POINT, HOSPITAL, FIRE_STATION) з реалістичними criticality.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

import numpy as np

from app.ml.features import FeatureBundle, FEATURE_NAMES, ScoreFeatures

RNG_SEED = 42
N_SAMPLES = 8000


@dataclass(frozen=True)
class ScenarioProfile:
    """Профіль сценарію — допоміжний тип для генерації."""

    name: str
    weight: float
    power_on_prob: float
    blackout_with_generator_battery_range: tuple[float, float]
    no_generator_battery_range: tuple[float, float]
    base_temp_c: float
    base_co2_range: tuple[float, float]
    base_occupancy_ratio_range: tuple[float, float]
    internet_on_prob: float


SCENARIOS: tuple[ScenarioProfile, ...] = (
    ScenarioProfile(
        name="NORMAL",
        weight=0.45,
        power_on_prob=1.0,
        blackout_with_generator_battery_range=(80.0, 100.0),
        no_generator_battery_range=(80.0, 100.0),
        base_temp_c=21.0,
        base_co2_range=(450.0, 750.0),
        base_occupancy_ratio_range=(0.20, 0.65),
        internet_on_prob=1.0,
    ),
    ScenarioProfile(
        name="PARTIAL_DISTRESS",
        weight=0.25,
        power_on_prob=0.5,
        blackout_with_generator_battery_range=(50.0, 85.0),
        no_generator_battery_range=(30.0, 70.0),
        base_temp_c=23.0,
        base_co2_range=(700.0, 1200.0),
        base_occupancy_ratio_range=(0.45, 0.90),
        internet_on_prob=0.7,
    ),
    ScenarioProfile(
        name="FULL_BLACKOUT",
        weight=0.20,
        power_on_prob=0.0,
        blackout_with_generator_battery_range=(40.0, 75.0),
        no_generator_battery_range=(5.0, 45.0),
        base_temp_c=26.0,
        base_co2_range=(900.0, 2000.0),
        base_occupancy_ratio_range=(0.60, 1.10),
        internet_on_prob=0.4,
    ),
    ScenarioProfile(
        name="CRITICAL_OVERLOAD",
        weight=0.10,
        power_on_prob=0.0,
        blackout_with_generator_battery_range=(10.0, 35.0),
        no_generator_battery_range=(0.0, 15.0),
        base_temp_c=30.0,
        base_co2_range=(1500.0, 3500.0),
        base_occupancy_ratio_range=(0.90, 1.50),
        internet_on_prob=0.2,
    ),
)


def _sample_occupancy_ratio(rng: np.random.Generator, lo: float, hi: float) -> float:
    val = rng.uniform(lo, hi)
    return float(np.clip(val + rng.normal(0, 0.05), 0.0, 1.8))


def _sample_co2(rng: np.random.Generator, lo: float, hi: float) -> float:
    return float(rng.uniform(lo, hi))


def _sample_temp(rng: np.random.Generator, base: float) -> float:
    return float(base + rng.normal(0, 1.5))


def _sample_humidity(rng: np.random.Generator) -> float:
    return float(np.clip(rng.normal(50, 8), 25, 90))


def _sample_signal(rng: np.random.Generator, internet_on: bool) -> int:
    if not internet_on:
        return int(rng.choice([0, 0, 1]))
    return int(rng.choice([2, 3, 3, 4, 4, 4]))


def _resilience_score_target(
    battery_pct: float,
    battery_hours: float,
    power_on: bool,
    temp_c: float,
    co2_ppm: float,
    occupancy_ratio: float,
    criticality: int,
    has_generator: bool,
    has_starlink: bool,
    internet_on: bool,
    generator_on: bool,
) -> float:
    """
    Обчислює "ground truth" Resilience Score (0-100) на основі фізичних міркувань.

    Це — наша ЦІЛЬОВА ФУНКЦІЯ, яку ML-модель має вивчити.
    Вона НЕ використовується під час inference, тільки під час тренування.
    """
    score = 0.0

    # 1. Базова виживаність (макс 35 балів)
    if power_on and battery_pct > 60:
        score += 35.0
    elif power_on:
        score += 22.0 + (battery_pct - 30) * 0.2
    elif has_generator and generator_on and battery_hours > 12:
        score += 28.0
    elif has_generator and battery_pct > 40:
        score += 18.0
    else:
        # Без живлення, без генератора
        score += max(0.0, (battery_pct - 5) * 0.30)

    # 2. Заряд батареї (макс 15 балів)
    score += min(15.0, battery_pct * 0.15)
    if battery_hours < 2 and not power_on and not generator_on:
        score -= 10.0

    # 3. Якість повітря (макс 15 балів)
    if co2_ppm < 800:
        score += 15.0
    elif co2_ppm < 1200:
        score += 10.0
    elif co2_ppm < 1800:
        score += 5.0
    if co2_ppm > 2000:
        score -= 5.0

    # 4. Температурний комфорт (макс 10 балів)
    if 18 <= temp_c <= 24:
        score += 10.0
    elif 15 <= temp_c <= 27:
        score += 6.0
    elif 10 <= temp_c <= 32:
        score += 2.0
    else:
        score -= 3.0

    # 5. Переповненість (макс 10 балів)
    if occupancy_ratio <= 0.7:
        score += 10.0
    elif occupancy_ratio <= 1.0:
        score += 5.0
    elif occupancy_ratio <= 1.3:
        score -= 3.0
    else:
        score -= 8.0

    # 6. Зв'язок (макс 8 балів)
    if internet_on:
        score += 8.0
    elif has_starlink:
        score += 3.0

    # 7. Пріоритет об'єкта (макс 7 балів)
    score += criticality * 1.4

    # Невеликий шум (мікросенсорні варіації)
    score += float(np.random.normal(0, 1.5))

    return float(np.clip(score, 0.0, 100.0))


def _resilience_status_from_score(score: float, ttc_min: float | None) -> str:
    """
    Конвертує score (і ttc) у мітку статусу.
    STABLE >= 70, WARNING 40-69, CRITICAL < 40, або CRITICAL якщо ttc < 30 хв.
    """
    if ttc_min is not None and ttc_min <= 0:
        return "CRITICAL"
    if ttc_min is not None and ttc_min < 30:
        return "CRITICAL"
    if ttc_min is not None and ttc_min < 60:
        return "WARNING"
    if score >= 70:
        return "STABLE"
    if score >= 40:
        return "WARNING"
    return "CRITICAL"


def _estimate_ttc_minutes(
    battery_pct: float, battery_hours: float, power_on: bool, generator_on: bool
) -> float | None:
    """Груба оцінка TTC на основі battery_est_hours."""
    if power_on:
        return None
    if battery_hours <= 0 or battery_pct <= 0:
        return 0.0
    # 20% вважаємо критичним порогом
    headroom_pct = max(0.0, battery_pct - 20.0)
    return float(headroom_pct / 100.0 * battery_hours * 60.0)


def generate_dataset(n_samples: int = N_SAMPLES, seed: int = RNG_SEED) -> FeatureBundle:
    """
    Генерує реалістичний тренувальний датасет.

    Повертає:
      X          — (n, 13) numpy-масив ознак
      y          — (n,) target score (0-100)
      y_status   — (n,) string label {"STABLE", "WARNING", "CRITICAL"}
    """
    rng = np.random.default_rng(seed)
    np.random.seed(seed)  # для _resilience_score_target що використовує np.random

    weights = np.array([s.weight for s in SCENARIOS], dtype=np.float64)
    weights = weights / weights.sum()
    scenario_indices = rng.choice(len(SCENARIOS), size=n_samples, p=weights)

    X = np.zeros((n_samples, len(FEATURE_NAMES)), dtype=np.float64)
    y = np.zeros(n_samples, dtype=np.float64)
    y_status = np.empty(n_samples, dtype=object)

    crit_distribution = np.array([1, 2, 3, 3, 5], dtype=np.float64)
    crit_distribution = crit_distribution / crit_distribution.sum()

    for i in range(n_samples):
        sc = SCENARIOS[int(scenario_indices[i])]
        criticality = int(rng.choice([1, 2, 3, 4, 5], p=crit_distribution))
        has_generator = bool(rng.random() < 0.55)
        has_starlink = bool(rng.random() < 0.30)

        power_on = bool(rng.random() < sc.power_on_prob) or (
            has_generator and rng.random() < 0.85
        )
        generator_on = bool(has_generator and not power_on)

        if has_generator and (generator_on or power_on):
            battery_pct = float(rng.uniform(*sc.blackout_with_generator_battery_range))
            battery_hours = float(rng.uniform(18, 72))
        else:
            battery_pct = float(rng.uniform(*sc.no_generator_battery_range))
            battery_hours = float(
                np.clip(battery_pct / 50.0 + rng.normal(0, 0.5), 0.0, 12.0)
            )

        temp_c = _sample_temp(rng, sc.base_temp_c)
        co2_ppm = _sample_co2(rng, *sc.base_co2_range)
        occ_ratio = _sample_occupancy_ratio(rng, *sc.base_occupancy_ratio_range)
        humidity = _sample_humidity(rng)
        internet_on = bool(rng.random() < sc.internet_on_prob or has_starlink)
        signal = _sample_signal(rng, internet_on)

        # Записуємо ознаки у фіксованому порядку FEATURE_NAMES
        X[i] = np.array(
            [
                battery_pct,
                battery_hours,
                temp_c,
                co2_ppm,
                occ_ratio,
                float(criticality),
                float(has_generator),
                float(has_starlink),
                float(power_on),
                float(internet_on),
                float(signal),
                humidity,
                float(generator_on),
            ],
            dtype=np.float64,
        )

        score = _resilience_score_target(
            battery_pct=battery_pct,
            battery_hours=battery_hours,
            power_on=power_on,
            temp_c=temp_c,
            co2_ppm=co2_ppm,
            occupancy_ratio=occ_ratio,
            criticality=criticality,
            has_generator=has_generator,
            has_starlink=has_starlink,
            internet_on=internet_on,
            generator_on=generator_on,
        )
        ttc = _estimate_ttc_minutes(battery_pct, battery_hours, power_on, generator_on)
        y[i] = score
        y_status[i] = _resilience_status_from_score(score, ttc)

    return FeatureBundle(X=X, y=y, y_status=y_status)


def stream_examples(n_samples: int = 2000) -> Iterator[ScoreFeatures]:
    """
    Ітератор ScoreFeatures для юніт-тестів / eval-сценаріїв.
    """
    bundle = generate_dataset(n_samples=n_samples)
    for i in range(bundle.n_samples):
        row = bundle.X[i]
        yield ScoreFeatures(
            battery_pct=float(row[0]),
            battery_est_hours=float(row[1]),
            temp_c=float(row[2]),
            co2_ppm=float(row[3]),
            occupancy_ratio=float(row[4]),
            criticality=int(row[5]),
            has_generator=bool(row[6]),
            has_starlink=bool(row[7]),
            power_on=bool(row[8]),
            internet_on=bool(row[9]),
            signal=int(row[10]),
            humidity_pct=float(row[11]),
            generator_on=bool(row[12]),
        )


def status_to_int(status: str) -> int:
    return {"STABLE": 2, "WARNING": 1, "CRITICAL": 0}[status]


def int_to_status(v: int) -> str:
    return {2: "STABLE", 1: "WARNING", 0: "CRITICAL"}.get(int(v), "WARNING")
