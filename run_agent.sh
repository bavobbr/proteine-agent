#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

echo "[1] Starting invisible browser (Xvfb)..."
./start_browser_xvfb.sh
sleep 5 # Brief pause for browser startup

echo "[2] Extracting data across all supermarkets..."
"$SCRIPT_DIR/venv/bin/python" extract_supermarkets.py

echo "[3] Analyzing promotions and sending Telegram notification..."
"$SCRIPT_DIR/venv/bin/python" analyze_promos.py

echo "[4] Cleaning up..."
pkill -f "remote-debugging-port=9222"
echo "Agent run completed!"
