#!/bin/bash
set -u
# macOS may mark downloaded files as quarantined; this script itself does not remove that flag.

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"
BASE_PORT="${PORT:-8090}"
PORT="$BASE_PORT"
APP_BUILD_ID="7.4.2-final"
if [ ! -f "$APP_DIR/static/index.html" ]; then
  echo "Ошибка: не найден $APP_DIR/static/index.html"
  read -r -p "Нажми Enter для выхода..."; exit 1
fi
LOG_FILE="$APP_DIR/outputs/server.log"
VENV="$APP_DIR/.venv"
mkdir -p "$APP_DIR/outputs"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 не найден."
  read -r -p "Нажми Enter для выхода..."; exit 1
fi

if [ ! -x "$VENV/bin/python" ]; then
  echo "Первый запуск: создаю виртуальное окружение..."
  python3 -m venv --system-site-packages "$VENV" || python3 -m venv "$VENV"
fi
PY="$VENV/bin/python"

if ! "$PY" -c 'import fastapi,uvicorn,multipart,dotenv,openai,pptx,PIL,fitz,pypdf,docx,requests' >/dev/null 2>&1; then
  echo "Устанавливаю зависимости..."
  "$PY" -m pip install -r requirements.txt || { echo "Не удалось установить зависимости."; read -r -p "Нажми Enter для выхода..."; exit 1; }
fi

if [ ! -f "$APP_DIR/.env" ]; then cp "$APP_DIR/.env.example" "$APP_DIR/.env"; fi

# Reuse only this exact build. A stale copy of the app on the same port is not accepted.
if curl -fsS --max-time 2 "http://127.0.0.1:${PORT}/api/version" | grep -q "$APP_BUILD_ID"; then
  open "http://127.0.0.1:${PORT}"
  echo "Digital Presentation Designer уже запущен: http://127.0.0.1:${PORT}"
  exit 0
fi
# First reclaim 8090 when it is occupied by an older copy of this same app.
# This prevents Safari/Finder from continuing to show a stale ai_presentation_designer_v2 server.
if command -v lsof >/dev/null 2>&1 && command -v ps >/dev/null 2>&1; then
  for PID_OLD in $(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true); do
    CMD_OLD="$(ps -p "$PID_OLD" -o command= 2>/dev/null || true)"
    if printf '%s' "$CMD_OLD" | grep -q 'uvicorn app:app'; then
      case "$CMD_OLD" in
        *"$APP_DIR"*) ;;
        *)
          echo "Обнаружен старый экземпляр приложения на порту $PORT. Останавливаю его…"
          kill "$PID_OLD" 2>/dev/null || true
          sleep 0.8
          ;;
      esac
    fi
  done
fi

# If another unrelated app still occupies the base port, find the next free local port.
if command -v lsof >/dev/null 2>&1 && lsof -tiTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  for CANDIDATE in $(seq "$((BASE_PORT+1))" "$((BASE_PORT+9))"); do
    if ! lsof -tiTCP:"$CANDIDATE" -sTCP:LISTEN >/dev/null 2>&1; then PORT="$CANDIDATE"; break; fi
  done
fi

nohup "$PY" -m uvicorn app:app --host 127.0.0.1 --port "$PORT" >> "$LOG_FILE" 2>&1 &
PID=$!
echo "$PID" > "$APP_DIR/.server.pid"
for _ in {1..60}; do
  if curl -fsS --max-time 2 "http://127.0.0.1:${PORT}/api/version" >/dev/null 2>&1; then
    open "http://127.0.0.1:${PORT}"
    echo "Digital Presentation Designer запущен: http://127.0.0.1:${PORT}"
    exit 0
  fi
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "Сервер завершился. Лог: $LOG_FILE"
    tail -n 100 "$LOG_FILE" 2>/dev/null || true
    read -r -p "Нажми Enter для выхода..."; exit 1
  fi
  sleep 0.5
done

echo "Не удалось дождаться запуска. Лог: $LOG_FILE"
tail -n 100 "$LOG_FILE" 2>/dev/null || true
read -r -p "Нажми Enter для выхода..."
