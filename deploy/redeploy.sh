#!/usr/bin/env bash
#
# Оновлення ResQHub на сервері одним запуском.
#
# Використання (з Git Bash, у корені проєкту):
#   bash deploy/redeploy.sh            # залити все і перебудувати що змінилось
#   bash deploy/redeploy.sh frontend   # перебудувати лише frontend
#   bash deploy/redeploy.sh backend    # перебудувати лише backend
#
# Docker сам перебудовує тільки те, де змінився код (решта — з кешу, швидко).
# База даних лежить у Docker-volume і при оновленні НЕ втрачається.

set -euo pipefail

DROPLET="root@64.226.67.86"
SERVICE="${1:-}"

# Корінь проєкту = батьківська тека цього скрипта
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "→ Пакую код і заливаю на сервер…"
tar czf - \
  --exclude='./frontend/node_modules' \
  --exclude='./frontend/.next' \
  --exclude='./.venv' \
  --exclude='./.git' \
  --exclude='./.playwright-mcp' \
  --exclude='*__pycache__*' \
  --exclude='*.pyc' \
  --exclude='*.db' --exclude='*.db-shm' --exclude='*.db-wal' --exclude='*.db-journal' \
  --exclude='*.joblib' \
  --exclude='*.jpeg' \
  . | ssh "$DROPLET" "rm -rf /opt/orbit && mkdir -p /opt/orbit && tar xzf - -C /opt/orbit"

echo "→ Перебудовую і перезапускаю контейнери…"
ssh "$DROPLET" "cd /opt/orbit/deploy && docker compose up -d --build ${SERVICE}"

echo ""
echo "✅ Готово → https://resqhub.systems"
