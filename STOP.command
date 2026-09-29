#!/bin/bash
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$APP_DIR/.server.pid"
if [ ! -f "$PID_FILE" ]; then
  echo "Сервер не запущен."
  read -r -p "Нажми Enter для выхода..."
  exit 0
fi
PID="$(cat "$PID_FILE" 2>/dev/null || true)"
if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
  COMMAND="$(ps -p "$PID" -o command=)"
  case "$COMMAND" in
    *"$APP_DIR/.venv/bin/python"*"uvicorn app:app"*) kill "$PID" ;;
    *) echo "PID относится к другому процессу; остановка отменена."; exit 1 ;;
  esac
  echo "Digital Presentation Designer остановлен."
else
  echo "Процесс уже завершён."
fi
rm -f "$PID_FILE"
read -r -p "Нажми Enter для выхода..."
