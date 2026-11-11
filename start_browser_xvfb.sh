#!/usr/bin/env bash
echo "Ensuring background Xvfb Chrome service (chrome-cdp-xvfb.service) is running on 127.0.0.1:9222..."
if systemctl --user start chrome-cdp-xvfb.service 2>/dev/null; then
  exit 0
fi

echo "Fallback: starting invisible multi-store browser (Xvfb) directly..."
pkill -f "remote-debugging-port=9222"
sleep 2

mkdir -p "$HOME/.config/chrome-ah-profile"

xvfb-run -a --server-args="-screen 0 1920x1080x24" \
  google-chrome-stable \
  --ozone-platform=x11 \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.config/chrome-ah-profile" \
  --disable-search-engine-choice-screen \
  --window-size=1920,1080 \
  "about:blank" &
