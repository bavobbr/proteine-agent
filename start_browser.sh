#!/usr/bin/env bash
# Start zichtbare (non-headless) Google Chrome met remote debugging
echo "Oude browsersessies op poort 9222 afsluiten..."
pkill -f "remote-debugging-port=9222"
sleep 1

mkdir -p "$HOME/.config/chrome-ah-profile"

echo "Zichtbare Google Chrome wordt gestart op je scherm..."
google-chrome-stable \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.config/chrome-ah-profile" \
  --window-size=1920,1080 \
  "about:blank" &

echo "Browser gestart! Draai nu: ./venv/bin/python extract_supermarkten.py"
