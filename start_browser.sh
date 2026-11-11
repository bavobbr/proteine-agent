#!/usr/bin/env bash
# Starts visible (non-headless) Google Chrome with remote debugging enabled
echo "Stopping background chrome-cdp-xvfb systemd service (if active)..."
systemctl --user stop chrome-cdp-xvfb.service 2>/dev/null || true

echo "Closing existing browser sessions on port 9222..."
pkill -f "remote-debugging-port=9222"
sleep 1

mkdir -p "$HOME/.config/chrome-ah-profile"

echo "Starting visible Google Chrome on your display..."
google-chrome-stable \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.config/chrome-ah-profile" \
  --disable-search-engine-choice-screen \
  --window-size=1920,1080 \
  "about:blank" &

echo "Browser started! (Note: run 'systemctl --user start chrome-cdp-xvfb.service' when done to restore the background service)"
