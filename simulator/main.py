"""
ResQHub Simulator — реалістичний генератор телеметрії для критичних
об'єктів міста. Фізика диференційована: кожен об'єкт має власну ємність
батареї (battery_capacity_wh), власне навантаження (тип + люди) і тому
власну швидкість деградації у блекаут.

  NORMAL        — мережа є, батареї заряджаються, occupancy живе за
                  добовим циклом, CO2/температура — функції людей.
  BLACKOUT      — мережа зникає. Об'єкти з генератором рятує АВР
                  (автозапуск) — вони живуть на пальному і не потребують
                  втручання. Об'єкти без генератора розряджають батарею
                  зі швидкістю load_w / capacity_wh — хтось за годину,
                  хтось тримається пів доби.
  PARTIAL_OUTAGE— те саме, але для одного району (scope target).
  SIGNAL_DOWN   — живлення є, зв'язок зник.
  RESET         — повернення до NORMAL.

Час прискорено: SIM_SPEEDUP секунд симуляції за 1 реальну секунду,
щоб деградація була видима на демо, але цифри (години автономності)
залишались реалістичними.

Запуск:
    python main.py             # Звичайний режим
    python main.py --demo      # Демо-режим для презентації
    python main.py --fast      # Прискорений інтервал (2с)
"""

from __future__ import annotations

import argparse
import asyncio
import math
import os
import random
import sys

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
INTERVAL_SEC = int(os.getenv("INTERVAL_SEC", "5"))

# 1 реальна секунда = SIM_SPEEDUP секунд симульованого часу.
# 60 → за хвилину демо проходить година «життя» об'єкта.
SIM_SPEEDUP = float(os.getenv("SIM_SPEEDUP", "60"))

# Об'єкти, які симулятор НЕ чіпає (кома-розділений список object_id).
# Потрібно для живого демо: реальний ESP32-вузол сам шле телеметрію свого
# об'єкта, і без цього виключення симулятор перезаписував би його стан
# кожні кілька секунд (мигання «є світло / нема»).
EXCLUDE_OBJECT_IDS = {
    x.strip() for x in os.getenv("EXCLUDE_OBJECT_IDS", "").split(",") if x.strip()
}

# Базове навантаження (Вт) за типом об'єкта + споживання на людину.
# Ті самі значення, що й на бекенді (orchestrator._BASE_LOAD_W).
BASE_LOAD_W = {
    "HOSPITAL": 4000.0,
    "FIRE_STATION": 1500.0,
    "SCHOOL": 800.0,
    "SHELTER": 600.0,
    "RESILIENCE_POINT": 400.0,
}
LOAD_PER_PERSON_W = 25.0

# Запас пального стаціонарного генератора (год симульованого часу).
GENERATOR_FUEL_HOURS = {
    "HOSPITAL": 48.0,
    "FIRE_STATION": 24.0,
    "RESILIENCE_POINT": 12.0,
    "SHELTER": 8.0,
    "SCHOOL": 8.0,
}


# ─── Terminal Colors ───────────────────────────────────────────────
class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    DIM = "\033[2m"


def log(msg: str, level: str = "info") -> None:
    prefix = {
        "info": f"{C.CYAN}[sim]{C.RESET}",
        "ok": f"{C.GREEN}[sim ✓]{C.RESET}",
        "warn": f"{C.YELLOW}[sim ⚠]{C.RESET}",
        "err": f"{C.RED}[sim ✗]{C.RESET}",
        "demo": f"{C.BLUE}{C.BOLD}[DEMO]{C.RESET}",
    }.get(level, f"[sim]")
    print(f"{prefix} {msg}")


# ─── State ─────────────────────────────────────────────────────────
@dataclass
class SimState:
    """Внутрішній стан симулятора по кожному об'єкту."""

    object_id: str
    object_name: str
    type: str
    district: str
    criticality: int
    capacity: int
    has_generator: bool
    has_starlink: bool

    battery_capacity_wh: float = 5000.0

    power_on: bool = True
    battery_pct: float = 100.0
    battery_est_hours: float = 24.0
    temp_c: float = 21.0
    humidity_pct: float = 45.0
    co2_ppm: float = 600.0
    signal: int = 4
    internet_on: bool = True
    occupancy: int = 30
    generator_on: bool = False
    fuel_hours: float = 8.0
    last_tick: float = field(default_factory=time.time)

    @property
    def load_w(self) -> float:
        """Поточне навантаження об'єкта у Вт."""
        base = BASE_LOAD_W.get(self.type, 800.0)
        return base + self.occupancy * LOAD_PER_PERSON_W

    def backup_hours(self) -> float:
        """Скільки годин протримається батарея з поточним навантаженням."""
        energy_wh = self.battery_capacity_wh * self.battery_pct / 100.0
        return energy_wh / max(self.load_w, 1.0)


states: list[SimState] = []
last_scenario_id: str | None = None


# ─── HTTP ──────────────────────────────────────────────────────────
async def http_get(client: httpx.AsyncClient, path: str) -> Any:
    r = await client.get(f"{BACKEND_URL}{path}", timeout=10)
    r.raise_for_status()
    return r.json()


async def http_post(client: httpx.AsyncClient, path: str, body: dict) -> Any:
    r = await client.post(f"{BACKEND_URL}{path}", json=body, timeout=10)
    r.raise_for_status()
    return r.json()


async def fetch_objects(client: httpx.AsyncClient) -> list[dict]:
    data = await http_get(client, "/api/objects")
    return data if isinstance(data, list) else []


async def fetch_active_scenario(client: httpx.AsyncClient) -> dict | None:
    try:
        data = await http_get(client, "/api/scenarios/active")
        return data if isinstance(data, dict) and data.get("id") else None
    except httpx.HTTPError:
        return None


async def fetch_backend_state(client: httpx.AsyncClient) -> dict[str, dict]:
    """Повертає {object_id: full_state} для синхронізації SimState з бекендом.

    Містить telemetry + властивості об'єкта (has_generator може змінитись,
    коли диспетчер доставив мобільний генератор).
    """
    try:
        data = await http_get(client, "/api/dashboard/full")
        return {o["id"]: o for o in data if o.get("id")}
    except httpx.HTTPError:
        return {}


# ─── Init ──────────────────────────────────────────────────────────
def init_states(objects: list[dict]) -> None:
    global states
    states = []
    for o in objects:
        if o["id"] in EXCLUDE_OBJECT_IDS:
            log(f"⏭  Пропускаю {o['name']} — керується реальним залізом", "warn")
            continue
        states.append(
            SimState(
                object_id=o["id"],
                object_name=o["name"],
                type=o["type"],
                district=o["district"],
                criticality=o["criticality"],
                capacity=o["capacity"],
                has_generator=o["has_generator"],
                has_starlink=o["has_starlink"],
                battery_capacity_wh=float(o.get("battery_capacity_wh", 5000.0)),
                occupancy=int(o["capacity"] * random.uniform(0.10, 0.30)),
                temp_c=21.0,
                co2_ppm=random.uniform(450, 650),
                battery_pct=100.0,
                battery_est_hours=24.0,
                signal=4,
                fuel_hours=GENERATOR_FUEL_HOURS.get(o["type"], 8.0),
            )
        )


# ─── Physics Ticks ─────────────────────────────────────────────────
def _occupancy_target(s: SimState) -> int:
    """Добовий цикл заповненості: вночі майже пусто, пік — вечір."""
    hour = time.localtime().tm_hour + time.localtime().tm_min / 60.0
    # Синусоїда з піком о 18:00: 5% вночі → ~35% ввечері
    day_curve = max(0.0, math.sin((hour - 6.0) / 24.0 * 2 * math.pi))
    frac = 0.05 + 0.30 * day_curve
    return int(s.capacity * frac)


def _drift_occupancy(s: SimState, target: int, rate: float = 0.15) -> None:
    """Плавно рухає occupancy до цільового значення (люди приходять/йдуть)."""
    delta = target - s.occupancy
    s.occupancy = max(0, s.occupancy + int(delta * rate) + random.randint(-2, 2))
    s.occupancy = min(s.occupancy, int(s.capacity * 1.2))


def _update_air(s: SimState, dt_sim_hours: float, ventilation_on: bool) -> None:
    """CO2 і температура — функції кількості людей та вентиляції."""
    density = s.occupancy / max(1, s.capacity)
    if ventilation_on:
        # Вентиляція тримає рівновагу: базовий рівень + внесок людей
        target_co2 = 450.0 + density * 500.0
        s.co2_ppm += (target_co2 - s.co2_ppm) * 0.3
        s.temp_c += (21.0 - s.temp_c) * 0.3
    else:
        # Без вентиляції CO2 накопичується пропорційно людям
        s.co2_ppm += density * 900.0 * dt_sim_hours
        # Без опалення температура повільно падає, але люди трохи гріють
        s.temp_c += (-2.0 + density * 3.0) * dt_sim_hours
    s.co2_ppm = max(420.0, min(3500.0, s.co2_ppm + random.uniform(-15, 15)))
    s.temp_c = max(5.0, min(35.0, s.temp_c + random.uniform(-0.1, 0.1)))
    s.humidity_pct = max(30.0, min(85.0, s.humidity_pct + random.uniform(-1, 1)))


def apply_normal_tick(s: SimState, dt_sec: float) -> None:
    """NORMAL: мережа є, батареї заряджаються, люди живуть своїм графіком."""
    dt_sim_hours = dt_sec * SIM_SPEEDUP / 3600.0
    s.power_on = True
    s.generator_on = False
    s.internet_on = True
    s.signal = 4
    # Батарея заряджається від мережі (~20%/сим-год), пальне поповнюється
    s.battery_pct = min(100.0, s.battery_pct + 20.0 * dt_sim_hours)
    s.fuel_hours = min(
        GENERATOR_FUEL_HOURS.get(s.type, 8.0), s.fuel_hours + 2.0 * dt_sim_hours
    )
    s.battery_est_hours = round(s.backup_hours(), 2)
    _drift_occupancy(s, _occupancy_target(s))
    _update_air(s, dt_sim_hours, ventilation_on=True)


def apply_blackout_tick(s: SimState, dt_sec: float) -> None:
    """BLACKOUT: мережа зникла.

    Об'єкти з генератором рятує АВР — генератор стартує автоматично і
    працює, поки є пальне. Об'єкти без генератора живуть на батареї:
    швидкість розряду = навантаження (тип + люди) / ємність батареї.
    Тому лікарня з 30 кВт·год і генератором «не помічає» блекаут,
    а маленька школа без генератора деградує за лічені години.
    """
    dt_sim_hours = dt_sec * SIM_SPEEDUP / 3600.0
    s.power_on = False
    s.internet_on = s.has_starlink
    s.signal = 3 if s.has_starlink else 1

    if s.has_generator and s.fuel_hours > 0.0:
        # АВР: генератор працює, батарея тримається, пальне вигорає
        s.generator_on = True
        s.fuel_hours = max(0.0, s.fuel_hours - dt_sim_hours)
        s.battery_pct = min(100.0, s.battery_pct + 10.0 * dt_sim_hours)
        s.battery_est_hours = round(s.fuel_hours, 2)
        # Живе укриття притягує людей з знеструмлених
        _drift_occupancy(s, int(s.capacity * 0.6), rate=0.05)
        _update_air(s, dt_sim_hours, ventilation_on=True)
        return

    # Без генератора (або пальне скінчилось): розряд батареї
    s.generator_on = False
    drain_wh = s.load_w * dt_sim_hours
    s.battery_pct = max(0.0, s.battery_pct - drain_wh / s.battery_capacity_wh * 100.0)
    s.battery_est_hours = round(s.backup_hours(), 2)

    # Люди залишають знеструмлене укриття, коли батарея сідає
    if s.battery_pct < 40.0:
        _drift_occupancy(s, int(s.occupancy * 0.5), rate=0.10)
    _update_air(s, dt_sim_hours, ventilation_on=False)


def apply_partial_outage_tick(s: SimState, dt_sec: float, target: str | None) -> None:
    """PARTIAL_OUTAGE: район з target знеструмлено."""
    if target is None or s.district == target:
        apply_blackout_tick(s, dt_sec)
    else:
        apply_normal_tick(s, dt_sec)


def apply_signal_down_tick(s: SimState, dt_sec: float) -> None:
    """SIGNAL_DOWN: живлення стабільне, зв'язок зник."""
    apply_normal_tick(s, dt_sec)
    s.internet_on = s.has_starlink
    s.signal = 3 if s.has_starlink else 0


def apply_reset_tick(s: SimState, dt_sec: float) -> None:
    """RESET: мережа повернулась, системи відновлюються поступово."""
    dt_sim_hours = dt_sec * SIM_SPEEDUP / 3600.0
    s.power_on = True
    s.generator_on = False
    s.internet_on = True
    s.signal = 4
    # Швидка зарядка після відновлення мережі
    s.battery_pct = min(100.0, s.battery_pct + 40.0 * dt_sim_hours)
    s.fuel_hours = GENERATOR_FUEL_HOURS.get(s.type, 8.0)
    s.battery_est_hours = round(s.backup_hours(), 2)
    _drift_occupancy(s, _occupancy_target(s))
    _update_air(s, dt_sim_hours, ventilation_on=True)


def step(scenario: dict | None) -> None:
    dt_sec = INTERVAL_SEC
    if scenario is None:
        for s in states:
            apply_normal_tick(s, dt_sec)
        return

    sc_type = scenario.get("type", "NORMAL")
    target = scenario.get("target")
    for s in states:
        if sc_type == "BLACKOUT":
            apply_blackout_tick(s, dt_sec)
        elif sc_type == "PARTIAL_OUTAGE":
            apply_partial_outage_tick(s, dt_sec, target)
        elif sc_type == "SIGNAL_DOWN":
            apply_signal_down_tick(s, dt_sec)
        elif sc_type == "RESET":
            apply_reset_tick(s, dt_sec)
        else:
            apply_normal_tick(s, dt_sec)


# ─── Push ──────────────────────────────────────────────────────────
async def push_telemetry(
    client: httpx.AsyncClient, active_scenario_id: str | None
) -> None:
    for s in states:
        body = {
            "object_id": s.object_id,
            "power_on": s.power_on,
            "battery_pct": round(s.battery_pct, 1),
            "battery_est_hours": round(s.battery_est_hours, 2),
            "temp_c": round(s.temp_c, 1),
            "humidity_pct": round(s.humidity_pct, 1),
            "co2_ppm": round(s.co2_ppm, 1),
            "signal": s.signal,
            "internet_on": s.internet_on,
            "occupancy": s.occupancy,
            "generator_on": s.generator_on,
            "scenario_id": active_scenario_id,
        }
        try:
            await http_post(client, "/api/telemetry", body)
        except httpx.HTTPError as e:
            log(f"POST telemetry failed for {s.object_name}: {e}", "err")


def print_status_bar() -> None:
    """Вивести компактну стрічку стану для терміналу."""
    online = sum(1 for s in states if s.power_on or s.generator_on)
    crit = sum(
        1 for s in states if s.battery_pct < 30 and not (s.power_on or s.generator_on)
    )
    gen = sum(1 for s in states if s.generator_on)
    avg_bat = sum(s.battery_pct for s in states) / max(1, len(states))
    total_occ = sum(s.occupancy for s in states)

    bar = (
        f"  {C.GREEN}●{C.RESET} Online: {online}/{len(states)}"
        f"  {C.RED}●{C.RESET} Critical: {crit}"
        f"  {C.YELLOW}⚡{C.RESET} Generators: {gen}"
        f"  {C.BLUE}🔋{C.RESET} Avg Battery: {avg_bat:.0f}%"
        f"  {C.CYAN}👥{C.RESET} People: {total_occ}"
    )
    print(f"\r{bar}", end="", flush=True)


async def sync_states_from_backend(client: httpx.AsyncClient) -> None:
    """Синхронізує SimState зі станом бекенду.

    Критично для персистентності доставлених ресурсів: коли диспетчер
    доставив мобільний генератор або Starlink, бекенд оновлює has_generator/
    has_starlink і телеметрію. Без цієї синхронізації наступний фізичний тік
    симулятора перезаписав би зв'язок/живлення назад (саме тому Starlink
    «вмикався і одразу вимикався»).
    """
    backend_state = await fetch_backend_state(client)
    for s in states:
        o = backend_state.get(s.object_id)
        if not o:
            continue
        # Обладнання об'єкта могло змінитись (мобільний генератор / Starlink)
        s.has_generator = bool(o.get("has_generator", s.has_generator))
        s.has_starlink = bool(o.get("has_starlink", s.has_starlink))
        t = o.get("telemetry")
        if not t:
            continue
        s.battery_pct = float(t.get("battery_pct", s.battery_pct))
        s.power_on = bool(t.get("power_on", s.power_on))
        s.internet_on = bool(t.get("internet_on", s.internet_on))
        backend_gen = bool(t.get("generator_on", s.generator_on))
        backend_est = float(t.get("battery_est_hours", s.battery_est_hours))
        # Якщо бекенд каже «генератор працює» з більшим запасом годин
        # (АВР при старті сценарію, доставка палива/генератора) — оновлюємо
        # локальний запас пального, щоб генератор не «заглух» одразу.
        if backend_gen and backend_est > s.fuel_hours:
            s.fuel_hours = backend_est
        s.generator_on = backend_gen
        s.battery_est_hours = backend_est


# ─── Demo Mode ─────────────────────────────────────────────────────
DEMO_SCRIPT = [
    # (delay_ticks, scenario_type, scope, target, intensity, description)
    (6, None, None, None, None, "Нормальна робота — всі об'єкти стабільні"),
    (0, "BLACKOUT", "CITY", None, 1.0, "⚡ БЛЕКАУТ — місто знеструмлено!"),
    (
        15,
        None,
        None,
        None,
        None,
        "Об'єкти з генераторами перейшли на АВР. Без генераторів — на батареях,"
        " і в кожного свій запас часу...",
    ),
    (0, "RESET", "CITY", None, 1.0, "🔄 ВІДНОВЛЕННЯ — живлення повернулось!"),
    (8, None, None, None, None, "Система відновлюється. Усі об'єкти стабілізуються."),
    (
        0,
        "PARTIAL_OUTAGE",
        "DISTRICT",
        "Богунія",
        1.0,
        "⚡ Часткове знеструмлення — район Богунія",
    ),
    (10, None, None, None, None, "Район Богунія деградує, решта — стабільна"),
    (0, "RESET", "CITY", None, 1.0, "🔄 Повне відновлення"),
    (6, None, None, None, None, "✅ Демонстрація завершена!"),
]


async def run_demo(client: httpx.AsyncClient) -> None:
    """Запуск демо-сценарію для презентації на хакатоні."""
    log("═══════════════════════════════════════════", "demo")
    log("  ResQHub DEMO MODE — Hackathon Presentation", "demo")
    log("═══════════════════════════════════════════", "demo")
    log("")

    for step_idx, (ticks, sc_type, scope, target, intensity, desc) in enumerate(
        DEMO_SCRIPT
    ):
        # Announce stage
        log(f"Stage {step_idx + 1}/{len(DEMO_SCRIPT)}: {desc}", "demo")

        # Trigger scenario if needed
        if sc_type is not None:
            try:
                body: dict[str, Any] = {
                    "type": sc_type,
                    "scope": scope or "CITY",
                    "intensity": intensity or 1.0,
                }
                if target:
                    body["target"] = target
                await http_post(client, "/api/scenarios", body)
                log(f"  → Сценарій {sc_type} активовано", "ok")
            except httpx.HTTPError as e:
                log(f"  → Помилка активації: {e}", "err")

        # Run physics ticks
        for tick in range(ticks):
            scenario = await fetch_active_scenario(client)
            sc_id = scenario.get("id") if scenario else None
            # Синхронізуємо доставлені ресурси (генератор/Starlink), щоб
            # ручні дії оператора під час демо не перезаписувались фізикою.
            await sync_states_from_backend(client)
            step(scenario)
            await push_telemetry(client, sc_id)
            print_status_bar()
            await asyncio.sleep(INTERVAL_SEC)

        print()  # newline after status bar

    log("")
    log(
        "Demo завершено! Натисніть Ctrl+C для виходу або чекайте — далі нормальний режим.",
        "demo",
    )
    log("")


# ─── Main ──────────────────────────────────────────────────────────
async def main(demo: bool = False, fast: bool = False) -> None:
    global INTERVAL_SEC

    if fast:
        INTERVAL_SEC = 2
        log(f"Прискорений режим: interval={INTERVAL_SEC}s", "warn")

    log(f"ResQHub Simulator -> {BACKEND_URL} (interval={INTERVAL_SEC}s)")

    async with httpx.AsyncClient() as client:
        # Чекаємо поки бекенд підніметься
        for attempt in range(30):
            try:
                await http_get(client, "/health")
                log("Бекенд доступний!", "ok")
                break
            except httpx.HTTPError:
                log(f"Очікуємо бекенд... (спроба {attempt + 1}/30)", "warn")
                await asyncio.sleep(2)
        else:
            log("Бекенд недоступний. Вихід.", "err")
            return

        objs = await fetch_objects(client)
        if not objs:
            log("Об'єкти відсутні. Запусти seed: python -m app.seed", "err")
            return
        init_states(objs)
        log(f"Імітація {len(states)} об'єктів → стартує.", "ok")

        # Print object list
        for s in states:
            gen_icon = "⚡" if s.has_generator else "  "
            star_icon = "📡" if s.has_starlink else "  "
            log(f"  {gen_icon} {star_icon} {s.object_name} ({s.district})")

        log("")

        if demo:
            await run_demo(client)

        # Normal loop (continues after demo too)
        global last_scenario_id
        while True:
            try:
                scenario = await fetch_active_scenario(client)
                sc_id = scenario.get("id") if scenario else None
                if sc_id != last_scenario_id:
                    sc_name = scenario.get("type") if scenario else "NORMAL"
                    log(f"Сценарій → {sc_name} (id={sc_id})")
                    last_scenario_id = sc_id
                # Синхронізуємо SimState зі станом бекенду, щоб backend-driven
                # зміни (сценарії, доставлені ресурси) не перезаписувались.
                await sync_states_from_backend(client)
                step(scenario)
                await push_telemetry(client, sc_id)
                print_status_bar()
            except httpx.ConnectError:
                print()
                log("Втрачено з'єднання з бекендом. Retry...", "err")
            except Exception as e:
                print()
                log(f"Помилка такту: {e!r}", "err")
            await asyncio.sleep(INTERVAL_SEC)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ResQHub Simulator")
    parser.add_argument(
        "--demo", action="store_true", help="Demo mode for presentation"
    )
    parser.add_argument("--fast", action="store_true", help="Fast interval (2s)")
    args = parser.parse_args()

    try:
        asyncio.run(main(demo=args.demo, fast=args.fast))
    except KeyboardInterrupt:
        print(f"\n{C.CYAN}[sim]{C.RESET} Зупинено.")
