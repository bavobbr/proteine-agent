#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

echo "[1] Ensuring invisible browser service (chrome-cdp-xvfb.service) is running..."
./start_browser_xvfb.sh
sleep 3 # Brief pause for browser readiness

echo "[2] Extracting data across all supermarkets..."
"$SCRIPT_DIR/venv/bin/python" extract_supermarkets.py

echo "[3] Analyzing promotions and sending Telegram notification..."
"$SCRIPT_DIR/venv/bin/python" analyze_promos.py

echo "Agent run completed!"
