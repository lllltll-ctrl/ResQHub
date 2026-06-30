"""
Seed-дані для ResQHub: критичні об'єкти міста Житомира.

Запуск:
    python -m app.seed
"""

from __future__ import annotations

import sys
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

from app.core.database import Base, SessionLocal, engine
from app.models.domain import Object, ObjectType
from app.services.orchestrator import create_object
from app.schemas import ObjectCreate


SEED_OBJECTS = [
    {
        "name": "Укриття — ЗОШ №25",
        "type": "SHELTER",
        "lat": 50.2597,
        "lon": 28.6647,
        "district": "Богунія",
        "address": "вул. Київська, 105",
        "criticality": 4,
        "capacity": 250,
        "battery_capacity_wh": 8000.0,
        "has_generator": True,
        "has_starlink": False,
    },
    {
        "name": "Укриття — ТЦ Glitch",
        "type": "SHELTER",
        "lat": 50.2645,
        "lon": 28.6578,
        "district": "Центр",
        "address": "пр. Незалежності, 12",
        "criticality": 3,
        "capacity": 400,
        "battery_capacity_wh": 12000.0,
        "has_generator": True,
        "has_starlink": True,
    },
    {
        "name": "ЗОШ №3",
        "type": "SCHOOL",
        "lat": 50.2615,
        "lon": 28.6789,
        "district": "Центр",
        "address": "вул. Велика Бердичівська, 30",
        "criticality": 3,
        "capacity": 500,
        "battery_capacity_wh": 6000.0,
        "has_generator": False,
        "has_starlink": False,
    },
    {
        "name": "Пункт незламності — Богунія",
        "type": "RESILIENCE_POINT",
        "lat": 50.2912,
        "lon": 28.6021,
        "district": "Богунія",
        "address": "вул. Ватутіна, 78",
        "criticality": 5,
        "capacity": 80,
        "battery_capacity_wh": 15000.0,
        "has_generator": True,
        "has_starlink": True,
    },
    {
        "name": "Лікарня ім. С.П. Корольова",
        "type": "HOSPITAL",
        "lat": 50.2741,
        "lon": 28.6456,
        "district": "Центр",
        "address": "вул. Вінницька, 104",
        "criticality": 5,
        "capacity": 220,
        "battery_capacity_wh": 30000.0,
        "has_generator": True,
        "has_starlink": True,
    },
    {
        "name": "Пожежна частина №2",
        "type": "FIRE_STATION",
        "lat": 50.2689,
        "lon": 28.6712,
        "district": "Центр",
        "address": "вул. Покровська, 10",
        "criticality": 5,
        "capacity": 50,
        "battery_capacity_wh": 10000.0,
        "has_generator": True,
        "has_starlink": False,
    },
    {
        "name": "Укриття — ЗОШ №15",
        "type": "SHELTER",
        "lat": 50.2510,
        "lon": 28.6895,
        "district": "Смоківка",
        "address": "вул. Чуднівська, 32",
        "criticality": 3,
        "capacity": 200,
        "battery_capacity_wh": 5000.0,
        "has_generator": False,
        "has_starlink": False,
    },
    {
        "name": "Пункт незламності — Смоківка",
        "type": "RESILIENCE_POINT",
        "lat": 50.2455,
        "lon": 28.6895,
        "district": "Смоківка",
        "address": "вул. Пушкінська, 1",
        "criticality": 4,
        "capacity": 60,
        "battery_capacity_wh": 7000.0,
        "has_generator": False,
        "has_starlink": True,
    },
    {
        "name": "Укриття — ЗОШ №21",
        "type": "SHELTER",
        "lat": 50.2734,
        "lon": 28.6234,
        "district": "Хмельницьке шосе",
        "address": "вул. Хмельницьке шосе, 17",
        "criticality": 3,
        "capacity": 180,
        "battery_capacity_wh": 4500.0,
        "has_generator": False,
        "has_starlink": False,
    },
    {
        "name": "Пункт незламності — Восток",
        "type": "RESILIENCE_POINT",
        "lat": 50.2725,
        "lon": 28.7120,
        "district": "Східний",
        "address": "вул. Щорса, 56",
        "criticality": 4,
        "capacity": 75,
        "battery_capacity_wh": 9000.0,
        "has_generator": True,
        "has_starlink": True,
    },
]


def seed() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        existing = db.query(Object).count()
        if existing > 0:
            print(f"БД вже містить {existing} об'єктів. Пропускаємо seed.")
            return
        print(f"Сідимо {len(SEED_OBJECTS)} об'єктів Житомира...")
        for item in SEED_OBJECTS:
            payload = ObjectCreate(**item)
            obj = create_object(db, payload)
            print(f"  [OK] {obj.name} ({obj.district})")
        print("Seed завершено.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
