#!/usr/bin/env bash
# Starts visible (non-headless) Google Chrome with remote debugging enabled
echo "Closing existing browser sessions on port 9222..."
pkill -f "remote-debugging-port=9222"
sleep 1

mkdir -p "$HOME/.config/chrome-ah-profile"

echo "Starting visible Google Chrome on your display..."
google-chrome-stable \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.config/chrome-ah-profile" \
  --window-size=1920,1080 \
  "about:blank" &

echo "Browser started! Now run: ./venv/bin/python extract_supermarkets.py"
