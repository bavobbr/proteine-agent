#!/usr/bin/env bash

cd /home/bavobbr/projects/proteine-agent

if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

echo "[1] Start onzichtbare browser (Xvfb)..."
pkill -f "remote-debugging-port=9222"
sleep 2

xvfb-run -a --server-args="-screen 0 1920x1080x24" \
  google-chrome-stable \
  --ozone-platform=x11 \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.config/chrome-ah-profile" \
  --window-size=1920,1080 \
  "about:blank" &

CHROME_PID=$!
sleep 5 # Korte pauze voor browser startup

echo "[2] Data extraheren over alle supermarkten..."
/home/bavobbr/projects/proteine-agent/venv/bin/python extract_supermarkten.py

echo "[3] Promoties analyseren en Telegram sturen..."
/home/bavobbr/projects/proteine-agent/venv/bin/python analyseer_promos.py

echo "[4] Opruimen..."
kill $CHROME_PID
pkill -f "remote-debugging-port=9222"
echo "Agent run voltooid!"