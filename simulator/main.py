"""
ResQHub Simulator — реалістичний генератор телеметрії для критичних
об'єктів міста. Враховує активний сценарій та фізичну логіку:

  NORMAL        — power_on=true, battery=100%, occupancy росте зранку
                  до піку вечора; стабільна температура/CO2.
  BLACKOUT      — power_on=false для всього міста, батарея втрачається
                  пропорційно навантаженню; occupancy поступово зменшується,
                  люди йдуть шукати живі укриття.
  PARTIAL_OUTAGE— power_on=false для конкретного району (scope target).
  SIGNAL_DOWN   — втрачається зв'язок для всього міста.
  RESET         — повернення до NORMAL.

Запуск:
    python main.py             # Звичайний режим
    python main.py --demo      # Демо-режим для презентації
    python main.py --fast      # Прискорений інтервал (2с)
"""

from __future__ import annotations

import argparse
import asyncio
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
    last_tick: float = field(default_factory=time.time)


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


# ─── Init ──────────────────────────────────────────────────────────
def init_states(objects: list[dict]) -> None:
    global states
    states = []
    for o in objects:
        occupancy = max(0, int(o["capacity"] * random.uniform(0.15, 0.40)))
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
                occupancy=occupancy,
                temp_c=random.uniform(20.0, 23.0),
            )
        )


# ─── Physics Ticks ─────────────────────────────────────────────────
def apply_normal_tick(s: SimState, dt_sec: float) -> None:
    """NORMAL: стабільне живлення, пульсація тиску протягом доби."""
    s.power_on = True
    if s.has_generator:
        s.generator_on = False
    s.internet_on = True
    s.signal = max(3, min(4, s.signal + random.choice([-1, 0, 0, 1])))
    s.battery_pct = min(100.0, s.battery_pct + 0.05 * dt_sec)
    s.battery_est_hours = 24.0
    # Добова пульсація люди
    hour = time.gmtime().tm_hour
    if 7 <= hour <= 22:
        target = int(s.capacity * (0.30 + 0.20 * abs((hour - 13) / 12)))
        s.occupancy += int((target - s.occupancy) * 0.05)
    else:
        s.occupancy -= int(s.occupancy * 0.02 * dt_sec / 5)
    s.occupancy = max(0, min(s.capacity, s.occupancy))
    s.temp_c += random.uniform(-0.1, 0.1) * dt_sec / 5
    s.temp_c = max(15.0, min(28.0, s.temp_c))
    s.co2_ppm = (
        500.0 + (s.occupancy / max(1, s.capacity)) * 600.0 + random.uniform(-30, 30)
    )
    s.humidity_pct += random.uniform(-0.5, 0.5)
    s.humidity_pct = max(30.0, min(70.0, s.humidity_pct))


def apply_blackout_tick(s: SimState, dt_sec: float) -> None:
    """BLACKOUT: зовнішнє живлення зникає, батарея втрачається."""
    s.internet_on = s.has_starlink
    s.signal = max(0, s.signal - 1) if not s.has_starlink else max(2, s.signal)
    if s.has_generator:
        # Генератор автоматично вмикається і забезпечує живленням
        s.generator_on = True
        s.power_on = True
        s.battery_pct = min(100.0, s.battery_pct + 1.0 * dt_sec / 5)
        s.battery_est_hours = 96.0
    else:
        s.generator_on = False
        s.power_on = False
        # Розряд: ~2 години до 0% (demo-швидкість). 100% / 7200сек = 0.0139%/сек
        load_factor = (s.occupancy / max(1, s.capacity)) * 0.10 + 0.90
        discharge_per_sec = 100.0 / (2.0 * 3600.0) * load_factor
        s.battery_pct = max(0.0, s.battery_pct - discharge_per_sec * dt_sec)
        # Час автономності зараз
        rate = discharge_per_sec * 3600.0
        s.battery_est_hours = (s.battery_pct / rate) if rate > 0 else 0.0
    # Люди йдуть шукати живі укриття якщо батарея < 30%
    if not s.has_generator and s.battery_pct < 30.0:
        s.occupancy = max(0, int(s.occupancy * (1 - 0.05 * dt_sec / 5)))
    s.temp_c += random.uniform(0.0, 0.15) * dt_sec / 5
    s.co2_ppm += 0 if s.occupancy == 0 else random.uniform(2, 8)
    s.co2_ppm = max(400.0, min(2500.0, s.co2_ppm))


def apply_partial_outage_tick(s: SimState, dt_sec: float, target: str | None) -> None:
    """PARTIAL_OUTAGE: район з target знеструмлено."""
    if target is None or s.district == target:
        apply_blackout_tick(s, dt_sec)
    else:
        apply_normal_tick(s, dt_sec)


def apply_signal_down_tick(s: SimState, dt_sec: float) -> None:
    """SIGNAL_DOWN: живлення стабільне, зв'язок зник."""
    apply_normal_tick(s, dt_sec)
    s.internet_on = False
    s.signal = 0


def apply_reset_tick(s: SimState, dt_sec: float) -> None:
    """RESET: повернення до норми."""
    apply_normal_tick(s, dt_sec)
    s.battery_pct = 100.0
    s.battery_est_hours = 24.0
    s.power_on = True
    s.generator_on = False
    s.internet_on = True
    s.signal = 4


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
    online = sum(1 for s in states if s.power_on)
    crit = sum(1 for s in states if s.battery_pct < 30 and not s.power_on)
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


# ─── Demo Mode ─────────────────────────────────────────────────────
DEMO_SCRIPT = [
    # (delay_ticks, scenario_type, scope, target, intensity, description)
    (6,  None,              None,       None,    None, "Нормальна робота — всі об'єкти стабільні"),
    (0,  "BLACKOUT",        "CITY",     None,    1.0,  "⚡ БЛЕКАУТ — місто знеструмлено!"),
    (15, None,              None,       None,    None, "Батареї розряджаються... Об'єкти деградують..."),
    (0,  "RESET",           "CITY",     None,    1.0,  "🔄 ВІДНОВЛЕННЯ — живлення повернулось!"),
    (8,  None,              None,       None,    None, "Система відновлюється. Усі об'єкти стабілізуються."),
    (0,  "PARTIAL_OUTAGE",  "DISTRICT", "Богунія", 1.0, "⚡ Часткове знеструмлення — район Богунія"),
    (10, None,              None,       None,    None, "Район Богунія деградує, решта — стабільна"),
    (0,  "RESET",           "CITY",     None,    1.0,  "🔄 Повне відновлення"),
    (6,  None,              None,       None,    None, "✅ Демонстрація завершена!"),
]


async def run_demo(client: httpx.AsyncClient) -> None:
    """Запуск демо-сценарію для презентації на хакатоні."""
    log("═══════════════════════════════════════════", "demo")
    log("  ResQHub DEMO MODE — Hackathon Presentation", "demo")
    log("═══════════════════════════════════════════", "demo")
    log("")

    for step_idx, (ticks, sc_type, scope, target, intensity, desc) in enumerate(DEMO_SCRIPT):
        # Announce stage
        log(f"Stage {step_idx + 1}/{len(DEMO_SCRIPT)}: {desc}", "demo")

        # Trigger scenario if needed
        if sc_type is not None:
            try:
                body: dict[str, Any] = {"type": sc_type, "scope": scope or "CITY", "intensity": intensity or 1.0}
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
            step(scenario)
            await push_telemetry(client, sc_id)
            print_status_bar()
            await asyncio.sleep(INTERVAL_SEC)

        print()  # newline after status bar

    log("")
    log("Demo завершено! Натисніть Ctrl+C для виходу або чекайте — далі нормальний режим.", "demo")
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
    parser.add_argument("--demo", action="store_true", help="Demo mode for presentation")
    parser.add_argument("--fast", action="store_true", help="Fast interval (2s)")
    args = parser.parse_args()

    try:
        asyncio.run(main(demo=args.demo, fast=args.fast))
    except KeyboardInterrupt:
        print(f"\n{C.CYAN}[sim]{C.RESET} Зупинено.")
