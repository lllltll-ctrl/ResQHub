# Доменна модель ResQHub

## Сутності

### Object (Критичний об'єкт міста)
- `id`: UUID
- `name`: string (наприклад, "Укриття — ЗОШ №25")
- `type`: enum [SHELTER, SCHOOL, RESILIENCE_POINT, HOSPITAL, FIRE_STATION]
- `lat`, `lon`: координати
- `district`: район міста
- `address`: текстова адреса
- `criticality`: 1-5 (1 — найменш критичний, 5 — найкритичніший)
- `capacity`: максимальна кількість людей
- `battery_capacity_wh`: ємність резервної батареї у Вт·год
- `has_generator`: bool
- `has_starlink`: bool
- `created_at`: datetime

### Telemetry (Телеметрія об'єкта)
- `id`: UUID
- `object_id`: FK → Object
- `ts`: datetime (UTC)
- `power_on`: bool (наявність електрики)
- `battery_pct`: 0-100 (заряд батареї)
- `battery_est_hours`: години автономної роботи за поточної витрат
- `temp_c`: температура °C
- `humidity_pct`: вологість %
- `co2_ppm`: CO₂ у ppm (якщо є сенсор)
- `signal`: 0-4 рівень сигналу
- `internet_on`: bool
- `occupancy`: поточна заповненість людей
- `generator_on`: bool
- `scenario_id`: nullable FK → Scenario (якщо подія тригерена сценарієм)

### Score (Розрахований Resilience Score)
- `id`: UUID
- `object_id`: FK → Object
- `ts`: datetime
- `score`: 0-100
- `status`: enum [STABLE, WARNING, CRITICAL, RESCUE_IN_TRANSIT]
- `time_to_critical_min`: хвилини до падіння у критичний стан (null = нескоро)
- `components`: JSONB (деталі розкладу score по факторах)

### Scenario (Симуляція / Демо-сценарій)
- `id`: UUID
- `type`: enum [NORMAL, BLACKOUT, PARTIAL_OUTAGE, SIGNAL_DOWN, RESET]
- `scope`: enum [CITY, DISTRICT, OBJECT] (об'єкт дії сценарію)
- `target`: nullable string (district name or object_id)
- `intensity`: 0-1 (наскільки сильно впливає)
- `started_at`: datetime
- `ended_at`: nullable datetime
- `is_active`: bool

### Assignment (Призначення ресурсу об'єкту)
- `id`: UUID
- `object_id`: FK → Object
- `resource_type`: enum [GENERATOR, BATTERY_BANK, STARLINK, TECH_TEAM, FUEL]
- `status`: enum [REQUESTED, DISPATCHED, ARRIVED, CANCELLED]
- `eta_min`: хвилини до прибуття
- `priority_score`: 0-100 (розраховується routing engine)
- `justification`: text (обґрунтування системи)
- `created_at`: datetime

### Event (Лог подій)
- `id`: UUID
- `ts`: datetime
- `object_id`: nullable FK → Object
- `scenario_id`: nullable FK → Scenario
- `type`: enum [STATUS_CHANGE, ALERT, ASSIGNMENT, SCENARIO_START, SCENARIO_END, MANUAL]
- `message`: text
- `severity`: enum [INFO, WARNING, ERROR]

## Логіка станів

```
STABLE (score ≥ 70) → WARNING (score 40-69) → CRITICAL (score < 40) → RESCUE_IN_TRANSIT (assigned)
                                ↑                              ↓
                                └─── after assignment arrival ──┘
```

## Типи об'єктів (демо-дані для Житомира)

Координати реальних районів Житомира (фокус хакатону):
- Shelter "Укриття ЗОШ №25" — 50.2597, 28.6647
- Shelter "Укриття ТЦ Glitch" — 50.2645, 28.6578
- School "ЗОШ №3" — 50.2615, 28.6789
- ResiliencePoint "Пункт незламності — Богунія" — 50.2912, 28.6021
- Hospital "Лікарня ім. С.П. Корольова" — 50.2741, 28.6456
- FireStation "Пожежна частина №2" — 50.2689, 28.6712

## Демо-сценарій

1. NORMAL — всі об'єкти green, score 80-95
2. BLACKOUT (city-wide) — power_on=false для всіх, батарея зменшується, статус переходить у WARNING/CRITICAL
3. Routing engine рекомендує направити генератор на 3 найбільш критичні об'єкти
4. Admin робить assignment → статус RESCUE_IN_TRANSIT → через N хвилин battery зростає, score повертається
5. Resident view показує оновлений список доступних пунктів