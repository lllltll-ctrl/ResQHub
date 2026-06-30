# ResQHub — міська платформа моніторингу енергостійкості Житомира

Система реального часу для координації та моніторингу критичних об'єктів міста (укриття, школи, пункти незламності, лікарні) під час відключень електроенергії та надзвичайних ситуацій.

## 📂 Структура проекту

*   `backend/` — FastAPI + SQLAlchemy + Alembic (Python 3.11/3.12)
*   `frontend/` — Next.js 14 + TypeScript + Tailwind + Leaflet + Zustand
*   `simulator/` — Asyncio-симулятор телеметрії об'єктів
*   `docs/` — Документація, доменна модель та Stitch специфікації

---

## 🧠 ML/AI Система (Production-ready)

### Архітектура (`backend/app/ml/`)

```
ml/
├── features.py         # Pydantic-валідація 13 фічей
├── dataset.py          # Реалістичний synthetic dataset (4 сценарії блекаутів)
├── train.py            # Training pipeline: RF + LightGBM ranker
├── inference.py        # Thread-safe load-once inference
├── store.py            # joblib-серіалізація з версіонуванням
├── explain.py          # SHAP-based пояснення
├── routing_ml.py       # Haversine + LightGBM ranker features
├── bayesian_forecast.py # Kalman Filter для time-to-critical
├── operator_briefing.py # Template/LLM-based operator narrative
└── monitoring/
    ├── drift.py        # Kolmogorov-Smirnov drift detection
    ├── anomaly.py      # Isolation Forest sensor anomaly
    └── vrp_solver.py   # PuLP-based Vehicle Routing Problem
```

### Моделі

| Модель | Тип | Метрики | Артефакт |
|---|---|---|---|
| **Resilience Score** | `RandomForestRegressor` (200 trees) | R²=0.993, accuracy=0.935, Brier<0.07 | `score_model_1.0.0.joblib` |
| **Priority Ranker** | `LightGBM lambdarank` | NDCG@5=1.000, NDCG@10=0.999 | `ranker_model_1.0.0.joblib` |
| **Anomaly Detector** | `IsolationForest` (200 trees) | contamination=0.05 | `anomaly_detector.joblib` |

### Тренування

```bash
cd backend
python -m app.ml.train
```

Метрики: RMSE, MAE, R², Brier, NDCG@5/@10, calibration plot (PNG), SHAP importance.

### ML Ops API (P2)

| Endpoint | Метод | Опис |
|---|---|---|
| `/api/ml/health` | GET | Стан усіх моделей |
| `/api/ml/versions` | GET | Активні версії + A/B config |
| `/api/ml/drift` | GET | Останній drift report |
| `/api/ml/drift/check` | GET | Запустити drift check |
| `/api/ml/drift/observe` | POST | Додати observation |
| `/api/ml/anomalies` | GET | Останні anomalies |
| `/api/ml/anomalies/score` | POST | Score single reading |
| `/api/ml/retrain` | POST | Async retrain (BackgroundTasks) |
| `/api/ml/ab/start` | POST | Запустити A/B тест |
| `/api/ml/ab/stop` | POST | Зупинити A/B тест |
| `/api/ml/briefing` | POST | Operator briefing (template/LLM) |

### A/B Testing

```bash
# Запустити A/B тест: 50% traffic на model v1.0.0, 50% на v1.1.0
curl -X POST http://localhost:8000/api/ml/ab/start \
  -H "Content-Type: application/json" \
  -d '{
    "model_a_version": "1.0.0",
    "model_b_version": "1.1.0",
    "traffic_split": 0.5
  }'
```

### Тести

```bash
cd backend
pytest tests/ -v
# 36/36 passing:
#   test_ml.py          (10 tests — features, dataset, inference)
#   test_monitoring.py  (11 tests — drift, anomaly, VRP)
#   test_bayesian.py    (7 tests — Kalman filter)
#   test_briefing.py    (8 tests — operator briefing)
```

---

## 🧠 Ключові інновації (Штучний інтелект та Логістика)

1.  **Machine Learning Score Engine:**
    `RandomForestRegressor` (на базі `scikit-learn`) для розрахунку Resilience Score. Модель навчена на синтетичних історичних датасетах блекаутів (4 сценарії), виявляє нелінійні залежності між швидкістю розряду батарей, зростанням CO₂ та переповненням об'єктів. **SHAP** для explainability.

2.  **Operations Research Routing:**
    - **LightGBM ranker** (`lambdarank`) для priority assignment
    - **PuLP-based VRP** з capacity constraints і time windows
    - **Hungarian algorithm** (scipy) як fallback
    - Haversine distance замість евклідової (точність на широті 50°)

3.  **Bayesian Time-to-Critical Forecast:**
    Kalman Filter з 95% confidence interval — оцінка невизначеності прогнозу розряду батареї.

4.  **Anomaly Detection (Isolation Forest):**
    Виявлення зламаних сенсорів та outlier readings у multivariate space.

5.  **Drift Detection (Kolmogorov-Smirnov):**
    Continuous monitoring розбіжностей між training distribution і live telemetry.

---

## ⚡ Швидкий старт

### 1. Backend

```bash
cd backend
python -m venv ../.venv
../.venv/Scripts/activate
pip install -r requirements.txt

cp .env.example .env
alembic upgrade head
python -m app.seed

# Тренування ML-моделей (один раз, або після зміни features)
python -m app.ml.train

uvicorn app.main:app --reload --port 8000
```

### 2. Simulator

```bash
cd simulator
../.venv/Scripts/activate
python main.py --demo
```

### 3. Frontend

```bash
cd frontend
pnpm install
pnpm dev
```

* Бекенд: http://localhost:8000
* API docs: http://localhost:8000/docs
* ML health: http://localhost:8000/api/ml/health
* Фронтенд: http://localhost:3000

---

## 🛠️ Технологічний стек

*   **Backend:** FastAPI, SQLAlchemy 2.0 (SQLite / PostgreSQL), Alembic, WebSockets, Pydantic v2
*   **Штучний інтелект та Аналітика:**
    * `scikit-learn` (RandomForestRegressor)
    * `scipy` (linear_sum_assignment, KS test)
    * `lightgbm` (lambdarank)
    * `shap` (TreeExplainer)
    * `pulp` (ILP solver)
    * `joblib` (model serialization)
*   **Frontend:** Next.js 14 (App Router), Tailwind CSS, Leaflet (React-Leaflet), Recharts, Zustand
*   **Simulator:** Asyncio, HTTPX

---

## 🔍 Troubleshooting

*   **`EADDRINUSE` (port already in use):**
    ```powershell
    netstat -ano | findstr :3000
    taskkill /F /PID <PID>
    ```
*   **База даних порожня:** запустіть `python -m app.seed` в `backend/`
*   **ML-модель не знайдена:** запустіть `python -m app.ml.train` в `backend/`
*   **Drift detector not initialized:** він ініціалізується lazy при першому `/api/ml/drift/check`
