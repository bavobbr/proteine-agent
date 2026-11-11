#!/usr/bin/env bash
echo "Starting invisible multi-store browser (Xvfb)..."
pkill -f "remote-debugging-port=9222"
sleep 2

mkdir -p "$HOME/.config/chrome-ah-profile"

xvfb-run -a --server-args="-screen 0 1920x1080x24" \
  google-chrome-stable \
  --ozone-platform=x11 \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.config/chrome-ah-profile" \
  --disable-search-engine-choice-screen \
  --window-size=1920,1080 \
  "about:blank" &
