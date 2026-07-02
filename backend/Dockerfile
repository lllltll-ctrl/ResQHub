FROM python:3.11-slim

WORKDIR /app

# libgomp1 — рантайм-залежність LightGBM
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Тренуємо ML-моделі під час build — артефакти (*.joblib) запікаються в образ
RUN python -m app.ml.train

EXPOSE 8000

# seed створює таблиці + 10 об'єктів Житомира (idempotent),
# далі API у ОДНОМУ воркері (WebSocket-стан живе в пам'яті процесу).
CMD ["sh", "-c", "python -m app.seed && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]
